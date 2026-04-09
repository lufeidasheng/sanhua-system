#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · language_bridge（企业版 v3.2+hotfix2）
作用：跨语言桥接（Python ↔ Rust/Go/C++/任意可执行体）
特性：BaseModule标准、沙箱（auto/docker/firejail/none）、健康检查、熔断、指标、热更新、
      异步执行线程（避免阻塞主循环）、输出截断、可选依赖（yaml/psutil）安全降级、事件总线兼容
"""

from __future__ import annotations
import os, sys, re, json, time, shutil, tempfile, asyncio
from typing import Dict, Any, Optional, Tuple, List, Awaitable, Callable

# --- 可选依赖（安全降级） ---
try:
    import yaml  # type: ignore
    _HAVE_YAML = True
except Exception:
    yaml = None
    _HAVE_YAML = False

try:
    import psutil  # type: ignore
    _HAVE_PSUTIL = True
except Exception:
    psutil = None
    _HAVE_PSUTIL = False

# ==== 三花聚顶基座 ====
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

log = get_logger("language_bridge")

# ========= 模块元信息 =========
__metadata__ = {
    "id": "language_bridge",
    "name": "语言桥接模块",
    "version": "3.2",
    "dependencies": ["psutil"],  # 可选降级，未安装也能跑（超时终止不如 psutil 精细）
    "entry_class": "modules.language_bridge.module.LanguageBridgeModule",
    "events": [
        "bridge.call", "bridge.health", "bridge.reload_config",
        "bridge.reset_cb", "bridge.runtimes", "bridge.list"
    ],
}

# ========= 常量 & 全局状态 =========
HEALTH_MAP = {"ok": "正常", "warning": "警告", "error": "错误", "critical": "严重", "degraded": "降级"}
DEFAULT_CFG_PATH = os.path.join(os.path.dirname(__file__), "bridges", "config.json")

SANDBOX_MODE = "auto"   # auto/docker/firejail/none
RUNTIME_CACHE: Dict[str, bool] = {}
BRIDGE_CFG: Dict[str, Dict[str, Any]] = {}      # bridge_name -> cfg
BRIDGE_REG: Dict[str, Callable[[str], Awaitable[str]]] = {}

HEALTH_STATUS = "ok"
MAX_STD_BYTES = 512 * 1024  # 每次调用最大返回512KB，避免外部程序刷爆内存

CALL_METRICS = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "last_error": None,
    "errors": {},  # code -> count
    "last_ts": 0.0,
}
CIRCUIT_BREAKER = {
    "enabled": False,
    "failure_threshold": 5,
    "reset_timeout": 60,   # seconds
    "last_failure": 0.0,
}

# ========= 异步执行线程（避免在主线程/GUI里 run_until_complete） =========
class AsyncRunner:
    """一个常驻的后台事件循环线程，安全执行异步任务"""
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread = None

    def _target(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def ensure_started(self):
        if self._thread and self._thread.is_alive():
            return
        import threading
        self._thread = threading.Thread(target=self._target, name="language-bridge-async", daemon=True)
        self._thread.start()
        # 等待事件循环可用
        for _ in range(50):
            if self._loop:
                break
            time.sleep(0.02)

    def submit(self, coro: Awaitable[Any]) -> Any:
        """同步等待异步结果（阻塞当前线程，但不抢系统主循环）"""
        self.ensure_started()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

ASYNC = AsyncRunner()

# ========= 工具 =========
def _bool_of(which: Optional[str]) -> bool:
    return which is not None and shutil.which(which) is not None

def detect_runtimes(force_refresh: bool = False) -> Dict[str, bool]:
    """带缓存的运行时检测"""
    global RUNTIME_CACHE
    if RUNTIME_CACHE and not force_refresh:
        return RUNTIME_CACHE
    runtimes = {
        "python": _bool_of("python3") or _bool_of("python"),
        "rust": _bool_of("cargo") or _bool_of("rustc"),
        "go": _bool_of("go"),
        "g++": _bool_of("g++"),
        "clang": _bool_of("clang"),
        "docker": _bool_of("docker"),
        "firejail": _bool_of("firejail"),
        "dotnet": _bool_of("dotnet"),
        "node": _bool_of("node"),
    }
    try:
        runtimes["python3.10+"] = sys.version_info >= (3, 10)
    except Exception:
        runtimes["python3.10+"] = False
    RUNTIME_CACHE = runtimes
    log.info(f"[bridge] 运行时检测：{runtimes}")
    return runtimes

def sanitize_input(s: str, pattern: Optional[str] = None) -> bool:
    """白名单校验（修复 ] 转义）"""
    pat = pattern or r"^[\w\s\-.,:;!?@(){}\[\]=+*/\\&%$#`~\"'|<>\u4e00-\u9fa5]+$"
    if len(s) > 4096:
        log.warning("[bridge] 输入超过最大长度限制")
        return False
    try:
        return bool(re.match(pat, s))
    except re.error as e:
        log.error(f"[bridge] 白名单正则非法：{e}")
        return False

def _normalize_command(base_dir: str, cmd: Any) -> List[str]:
    """命令路径归一化"""
    if isinstance(cmd, str):
        cmd = [cmd]
    if not cmd:
        return []
    first = cmd[0]
    if not os.path.isabs(first):
        cmd[0] = os.path.abspath(os.path.join(base_dir, first))
    return cmd

def _normalize_workdir(base_dir: str, workdir: Optional[str]) -> Optional[str]:
    if not workdir:
        return None
    return os.path.abspath(workdir if os.path.isabs(workdir) else os.path.join(base_dir, workdir))

def _inc_err(code: str):
    CALL_METRICS["errors"].setdefault(code, 0)
    CALL_METRICS["errors"][code] += 1

def _truncate_bytes(b: bytes, limit: int) -> bytes:
    if len(b) <= limit:
        return b
    # 使用 ASCII 提示，避免 bytes 非 ASCII 语法报错
    note = b"\n[... truncated: output exceeds limit ...]"
    return b[: max(0, limit - len(note))] + note

# ========= 配置加载 =========
def load_bridge_config(config_path: Optional[str] = None) -> bool:
    """加载 JSON/YAML 配置；归一化路径；无 yaml 时拒绝解析 yaml"""
    global BRIDGE_CFG
    path = config_path or DEFAULT_CFG_PATH
    if not os.path.exists(path):
        log.warning(f"[bridge] 配置文件不存在：{path}")
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            if path.endswith(".json"):
                cfg = json.load(f)
            elif path.endswith((".yaml", ".yml")):
                if not _HAVE_YAML:
                    log.error("[bridge] 缺少 PyYAML 依赖，无法解析 YAML 配置，请改用 JSON")
                    return False
                cfg = yaml.safe_load(f)  # type: ignore
            else:
                log.error("[bridge] 不支持的配置文件格式（仅支持 .json/.yaml/.yml）")
                return False

        base_dir = os.path.dirname(path)
        for name, item in (cfg or {}).items():
            item = item or {}
            item["command"] = _normalize_command(base_dir, item.get("command"))
            item["workdir"] = _normalize_workdir(base_dir, item.get("workdir"))
            cfg[name] = item
        BRIDGE_CFG = cfg or {}
        log.info(f"[bridge] 从 {path} 加载 {len(BRIDGE_CFG)} 个桥接配置")
        return True
    except Exception as e:
        log.error(f"[bridge] 加载配置失败：{e}")
        return False

def init_default_config() -> None:
    """内置缺省配置（可执行体请自行放到 bridges 目录）"""
    base = os.path.join(os.path.dirname(__file__), "bridges")
    BRIDGE_CFG.update({
        "rust_example": {
            "command": [os.path.join(base, "rust_example")],
            "requires": ["rust"],
            "description": "Rust示例桥接器",
            "sandbox": "auto",
            "timeout": 8,
        },
        "go_example": {
            "command": [os.path.join(base, "go_example")],
            "requires": ["go"],
            "description": "Go示例桥接器",
            "timeout": 10,
            "sanitize_pattern": r"^[\w\s\-.,:;!?]+$",
        },
        "cpp_example": {
            "command": [os.path.join(base, "cpp_example")],
            "requires": ["g++"],
            "description": "C++示例桥接器",
            "sandbox": "firejail",
            "timeout": 8,
        },
    })
    if sys.platform == "win32":
        for item in BRIDGE_CFG.values():
            if item.get("command"):
                item["command"][0] += ".exe"

# ========= 注册/反注册 =========
def register_bridge(name: str, coro: Callable[[str], Awaitable[str]], cfg: Dict[str, Any]):
    if not asyncio.iscoroutinefunction(coro):
        raise TypeError(f"[bridge] {name} 必须是异步函数")
    BRIDGE_REG[name] = coro
    log.info(f"[bridge] 已注册桥接器：{name}")

def unregister_bridge(name: str):
    if name in BRIDGE_REG:
        del BRIDGE_REG[name]
        log.info(f"[bridge] 已取消桥接器：{name}")

# ========= 安全执行 =========
async def _kill_process_tree(pid: int):
    """尽力杀掉子进程树（无 psutil 时退化为直接 kill）"""
    try:
        if _HAVE_PSUTIL:
            parent = psutil.Process(pid)  # type: ignore
            for ch in parent.children(recursive=True):
                ch.kill()
            parent.kill()
        else:
            import signal, os as _os
            _os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

async def execute_safely(
    command: List[str],
    input_data: Optional[str] = None,
    timeout: int = 10,
    sandbox: str = "none",
    workdir: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, str, int]:
    """安全执行外部命令（支持：none/docker/firejail）"""
    # 熔断器
    if CIRCUIT_BREAKER["enabled"] and (time.time() - CIRCUIT_BREAKER["last_failure"] < CIRCUIT_BREAKER["reset_timeout"]):
        return "", "Circuit breaker active", -10

    temp_dir = tempfile.mkdtemp(prefix="bridge_")
    cwd = workdir or temp_dir
    exec_cmd = list(command)
    cmd0 = exec_cmd[0] if exec_cmd else ""

    try:
        # 输入写入文件（按需）
        if input_data:
            ipath = os.path.join(cwd, "input.dat")
            os.makedirs(cwd, exist_ok=True)
            with open(ipath, "w", encoding="utf-8") as f:
                f.write(input_data)
            exec_cmd.append(ipath)

        # 沙箱
        runtimes = detect_runtimes()
        mode = sandbox
        if sandbox == "auto":
            if runtimes.get("docker"):
                mode = "docker"
            elif runtimes.get("firejail"):
                mode = "firejail"
            else:
                mode = "none"

        if mode == "docker" and runtimes.get("docker"):
            exec_cmd = [
                "docker", "run", "--rm",
                "-v", f"{cwd}:/data",
                "--workdir=/data",
                "--network=none",
                "--memory=256m",
                "--cpus=0.5",
                "python:3.11-slim"  # 示例镜像，生产请替换为内部受控镜像
            ] + exec_cmd
            cwd = None  # docker 内部工作目录已指定

        elif mode == "firejail" and runtimes.get("firejail"):
            exec_cmd = [
                "firejail", "--quiet",
                f"--private={cwd}",
                "--net=none", "--seccomp", "--rlimit-as=256m"
            ] + exec_cmd

        # 精简环境变量（避免继承危险变量）
        envp = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
            "NO_PROXY": "*",
            "HTTPS_PROXY": "",
            "HTTP_PROXY": "",
        }
        if env:
            envp.update(env)

        # 执行
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=envp,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await _kill_process_tree(proc.pid)
            return "", "Execution timeout", -1
        finally:
            dt = time.time() - t0
            # 避免长命令刷屏，只打头部片段
            head = " ".join(exec_cmd[:4]) if exec_cmd else "<empty>"
            log.debug(f"[bridge] 执行耗时 {dt:.2f}s：{head} ...")

        # 限制输出大小
        out = _truncate_bytes(out or b"", MAX_STD_BYTES)
        err = _truncate_bytes(err or b"", MAX_STD_BYTES)

        return out.decode(errors="ignore").strip(), err.decode(errors="ignore").strip(), proc.returncode

    except FileNotFoundError:
        return "", f"Command not found: {cmd0}", -2
    except Exception as e:
        log.error(f"[bridge] 执行异常：{e}")
        return "", f"Execution error: {e}", -3
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

# ========= 统一调用 =========
async def call_external_bridge(bridge_name: str, input_text: str, timeout: int = 5) -> str:
    global HEALTH_STATUS
    CALL_METRICS["total"] += 1
    CALL_METRICS["last_ts"] = time.time()

    if HEALTH_STATUS in ("critical", "error"):
        _inc_err("module_unhealthy")
        return "错误：模块处于异常状态"

    cfg = BRIDGE_CFG.get(bridge_name)
    if not cfg:
        CALL_METRICS["failed"] += 1
        _inc_err("config_missing")
        return f"错误：未配置的桥接器 {bridge_name}"

    # 输入校验
    if not sanitize_input(input_text, cfg.get("sanitize_pattern")):
        CALL_METRICS["failed"] += 1
        _inc_err("invalid_input")
        return "错误：输入包含非法字符"

    # 依赖检查
    runs = detect_runtimes()
    requires = cfg.get("requires", [])
    miss = [r for r in requires if not runs.get(r)]
    if miss:
        CALL_METRICS["failed"] += 1
        _inc_err("missing_runtime")
        return f"错误：缺少运行时依赖 {miss}"

    # 执行
    try:
        stdout, stderr, rc = await execute_safely(
            cfg.get("command", []),
            input_data=input_text,
            timeout=cfg.get("timeout", timeout),
            sandbox=cfg.get("sandbox", SANDBOX_MODE),
            workdir=cfg.get("workdir"),
            env=cfg.get("env"),
        )
        if rc != 0:
            CALL_METRICS["failed"] += 1
            CALL_METRICS["last_error"] = stderr or f"exit {rc}"
            _inc_err(f"exit_{rc}")
            CIRCUIT_BREAKER["last_failure"] = time.time()
            if CALL_METRICS["failed"] > CIRCUIT_BREAKER["failure_threshold"]:
                CIRCUIT_BREAKER["enabled"] = True
                HEALTH_STATUS = "critical"
                log.critical(f"[bridge] 熔断器触发：{bridge_name}")
            return f"错误：{stderr or f'外部程序执行失败(code={rc})'}"

        CALL_METRICS["success"] += 1
        return stdout

    except Exception as e:
        CALL_METRICS["failed"] += 1
        CALL_METRICS["last_error"] = str(e)
        _inc_err("exception")
        return f"错误：内部异常 - {e}"

# ========= 标准模块实现 =========
class LanguageBridgeModule(BaseModule):
    VERSION = "3.2"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self._registered = False
        self.config = getattr(meta, "config", {}) if meta else {}
        CIRCUIT_BREAKER.update(self.config.get("circuit_breaker", {}))
        log.info(f"[bridge] 初始化完成 v{self.VERSION}")

    # 生命周期
    def preload(self):
        self._register_actions()
        # 订阅事件
        if hasattr(self.context, "event_bus") and self.context.event_bus:
            bus = self.context.event_bus
            for ev in ("bridge.call", "bridge.health", "bridge.reload_config", "bridge.reset_cb", "bridge.runtimes", "bridge.list"):
                bus.subscribe(ev, self.handle_event)
        log.info("[bridge] preload 完成")

    def setup(self):
        # 加载配置
        cfg_path = self.config.get("config_path", DEFAULT_CFG_PATH)
        if not load_bridge_config(cfg_path):
            log.warning("[bridge] 使用内置默认配置")
            init_default_config()

        # 注册桥接器为异步函数
        for name, cfg in BRIDGE_CFG.items():
            async def _call(txt: str, _name=name):
                return await call_external_bridge(_name, txt)
            register_bridge(name, _call, cfg)

        # 运行时检测
        detect_runtimes()
        # 决策默认沙箱
        global SANDBOX_MODE
        SANDBOX_MODE = self.config.get("sandbox_mode", "auto")
        log.info(f"[bridge] setup 完成（sandbox={SANDBOX_MODE}）")

    def start(self):
        log.info("[bridge] 启动完成")

    def stop(self):
        BRIDGE_REG.clear()
        CIRCUIT_BREAKER["enabled"] = False
        log.info("[bridge] 停止并清理完成")

    def cleanup(self):
        log.info("[bridge] cleanup 完成")

    def health_check(self) -> Dict[str, Any]:
        status_cn = HEALTH_MAP.get(HEALTH_STATUS, HEALTH_STATUS)
        return {
            "status": status_cn,
            "module": getattr(self.meta, "name", "language_bridge"),
            "version": self.VERSION,
            "runtimes": detect_runtimes(),
            "bridge_count": len(BRIDGE_CFG),
            "metrics": CALL_METRICS,
            "circuit_breaker": CIRCUIT_BREAKER["enabled"],
            "timestamp": time.time(),
        }

    # 事件入口（兼容字符串/对象/字典）
    def handle_event(self, event, *args, **kwargs):
        try:
            if hasattr(event, "name"):
                name = getattr(event, "name", "")
                data = getattr(event, "data", {}) or {}
            elif isinstance(event, dict):
                name = event.get("name", "")
                data = event.get("data", {}) or {}
            else:
                name = str(event or "")
                data = kwargs.get("data", {}) or {}

            if name == "bridge.call":
                bname = data.get("name")
                text = data.get("input", "")
                if not bname:
                    return "错误：缺少桥接器名称"
                if bname not in BRIDGE_REG:
                    return f"错误：未知桥接器 {bname}"
                result = ASYNC.submit(BRIDGE_REG[bname](text))
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.call.done", {"name": bname, "result": result})
                return result

            if name == "bridge.health":
                h = self.health_check()
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.health.done", h)
                return h

            if name == "bridge.reload_config":
                path = data.get("config_path")
                ok = load_bridge_config(path)
                if ok:
                    BRIDGE_REG.clear()
                    for n, cfg in BRIDGE_CFG.items():
                        async def _call(txt: str, _name=n):
                            return await call_external_bridge(_name, txt)
                        register_bridge(n, _call, cfg)
                res = {"status": "success" if ok else "failed", "bridges": list(BRIDGE_CFG.keys())}
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.reload_config.done", res)
                return res

            if name == "bridge.reset_cb":
                CIRCUIT_BREAKER["enabled"] = False
                CIRCUIT_BREAKER["last_failure"] = 0.0
                global HEALTH_STATUS
                HEALTH_STATUS = "ok"
                res = {"status": "reset"}
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.reset_cb.done", res)
                return res

            if name == "bridge.runtimes":
                runs = detect_runtimes(True)
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.runtimes.done", runs)
                return runs

            if name == "bridge.list":
                lst = {"bridges": list(BRIDGE_CFG.keys())}
                if self.context and getattr(self.context, "event_bus", None):
                    self.context.event_bus.publish("bridge.list.done", lst)
                return lst

            log.debug(f"[bridge] 忽略事件：{name}")
            return None
        except Exception as e:
            log.error(f"[bridge] handle_event 异常：{e}")
            return {"error": str(e)}

    # ===== 动作实现（标准签名：context=None, params=None, **kwargs） =====
    def action_bridge_call(self, context=None, params=None, **kwargs):
        p = params or {}
        name = p.get("name")
        text = p.get("input", "")
        if not name:
            return "错误：缺少桥接器名称"
        if name not in BRIDGE_REG:
            return f"错误：未知桥接器 {name}"
        return ASYNC.submit(BRIDGE_REG[name](text))

    def action_bridge_health(self, context=None, params=None, **kwargs):
        return self.health_check()

    def action_bridge_reload(self, context=None, params=None, **kwargs):
        p = params or {}
        ok = load_bridge_config(p.get("config_path"))
        if ok:
            BRIDGE_REG.clear()
            for n, cfg in BRIDGE_CFG.items():
                async def _call(txt: str, _name=n):
                    return await call_external_bridge(_name, txt)
                register_bridge(n, _call, cfg)
        return {"status": "success" if ok else "failed", "bridges": list(BRIDGE_CFG.keys())}

    def action_bridge_reset_cb(self, context=None, params=None, **kwargs):
        CIRCUIT_BREAKER["enabled"] = False
        CIRCUIT_BREAKER["last_failure"] = 0.0
        global HEALTH_STATUS
        HEALTH_STATUS = "ok"
        return {"status": "reset"}

    def action_bridge_list(self, context=None, params=None, **kwargs):
        return {"bridges": list(BRIDGE_CFG.keys())}

    def action_bridge_runtimes(self, context=None, params=None, **kwargs):
        return detect_runtimes(True)

    # ===== 注册动作 =====
    def _register_actions(self):
        if self._registered:
            return
        ACTION_DISPATCHER.register_action(
            name="bridge.call", func=self.action_bridge_call,
            description="调用外部桥接器（跨语言）", permission="user", module="language_bridge"
        )
        ACTION_DISPATCHER.register_action(
            name="bridge.health", func=self.action_bridge_health,
            description="桥接模块健康检查", permission="user", module="language_bridge"
        )
        ACTION_DISPATCHER.register_action(
            name="bridge.reload_config", func=self.action_bridge_reload,
            description="重载桥接配置", permission="admin", module="language_bridge"
        )
        ACTION_DISPATCHER.register_action(
            name="bridge.reset_cb", func=self.action_bridge_reset_cb,
            description="重置熔断器", permission="admin", module="language_bridge"
        )
        ACTION_DISPATCHER.register_action(
            name="bridge.list", func=self.action_bridge_list,
            description="列出可用桥接器", permission="user", module="language_bridge"
        )
        ACTION_DISPATCHER.register_action(
            name="bridge.runtimes", func=self.action_bridge_runtimes,
            description="检测运行时环境", permission="user", module="language_bridge"
        )
        self._registered = True
        log.info("[bridge] 动作注册完成：bridge.call / bridge.health / bridge.reload_config / bridge.reset_cb / bridge.list / bridge.runtimes")


# ==== 热插拔脚手架 ====
def register_actions(dispatcher, context=None):
    mod = LanguageBridgeModule(meta=getattr(dispatcher, "get_module_meta", lambda *_: None)("language_bridge"), context=context)
    dispatcher.register_action("bridge.call", mod.action_bridge_call, description="调用外部桥接器（跨语言）", permission="user", module="language_bridge")
    dispatcher.register_action("bridge.health", mod.action_bridge_health, description="桥接模块健康检查", permission="user", module="language_bridge")
    dispatcher.register_action("bridge.reload_config", mod.action_bridge_reload, description="重载桥接配置", permission="admin", module="language_bridge")
    dispatcher.register_action("bridge.reset_cb", mod.action_bridge_reset_cb, description="重置熔断器", permission="admin", module="language_bridge")
    dispatcher.register_action("bridge.list", mod.action_bridge_list, description="列出可用桥接器", permission="user", module="language_bridge")
    dispatcher.register_action("bridge.runtimes", mod.action_bridge_runtimes, description="检测运行时环境", permission="user", module="language_bridge")
    log.info("[bridge] register_actions 完成")


# ==== 内嵌元数据（无需外置 manifest 也可被发现）====
MODULE_METADATA = {
    "name": "language_bridge",
    "version": LanguageBridgeModule.VERSION,
    "description": "跨语言桥接模块：外部可执行体/多语言插件的统一调用与管控。",
    "author": "三花聚顶开发团队",
    "entry": "modules.language_bridge",
    "actions": [
        {"name": "bridge.call", "description": "调用外部桥接器（跨语言）", "permission": "user"},
        {"name": "bridge.health", "description": "桥接模块健康检查", "permission": "user"},
        {"name": "bridge.reload_config", "description": "重载桥接配置", "permission": "admin"},
        {"name": "bridge.reset_cb", "description": "重置熔断器", "permission": "admin"},
        {"name": "bridge.list", "description": "列出可用桥接器", "permission": "user"},
        {"name": "bridge.runtimes", "description": "检测运行时环境", "permission": "user"},
    ],
    "dependencies": ["psutil"],
    "config_schema": {
        "sandbox_mode": {"type": "string", "enum": ["auto", "docker", "firejail", "none"], "default": "auto"},
        "config_path": {"type": "string", "default": DEFAULT_CFG_PATH},
        "circuit_breaker": {
            "type": "object",
            "properties": {
                "failure_threshold": {"type": "integer", "default": 5},
                "reset_timeout": {"type": "integer", "default": 60}
            }
        }
    },
}

MODULE_CLASS = LanguageBridgeModule

if __name__ == "__main__":
    # 简单自测：需放置 bridges/* 可执行体或修改 DEFAULT_CFG_PATH
    m = LanguageBridgeModule(meta=type("M", (), {"config": {}})(), context=None)
    m.preload(); m.setup(); m.start()
    print(m.health_check())
