#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌸 三花聚顶 · CLI旗舰入口 v4.4.2
cmd.Cmd标准shell | 主控run非阻塞 | 模块/动作/命令全链路调试输出 | 健康检查结构化
"""

import sys, os, argparse, signal, time, logging, readline, yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime
import cmd

__version__ = "4.4.2"
DEFAULT_CONFIG_DIR = "config"
DEFAULT_MODULES_DIR = "modules"
HISTORY_FILE = os.path.expanduser("~/.sanhua_history")
MAX_HISTORY_LINES = 1000
EMOJI = {
    "ok": "✅", "fail": "❌", "warn": "⚠️", "exit": "👋", "mod": "🧩", "act": "🤖", "star": "🌸",
    "success": "🌿", "error": "💢", "warn2": "🔥", "exit2": "🛤️", "module": "🧬", "action": "🖇️", "system": "🌐"
}

class AppMode(Enum):
    CLI = "cli"
    GUI = "gui"
    API = "api"
    VOICE = "voice"

def find_project_root(*markers) -> Tuple[Path, Path]:
    cur = Path(__file__).absolute().parent
    for _ in range(12):
        for marker in markers:
            if (cur / marker).exists():
                return cur, cur / marker
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError(f"未找到项目根目录（tried: {markers}）")

def load_config(global_path: Path, user_path: Path) -> dict:
    def _load(p, required):
        if not p.exists():
            if required:
                raise FileNotFoundError(f"缺少配置: {p}")
            return {}
        with p.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    def _merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and k in a:
                a[k] = _merge(a.get(k, {}), v)
            else:
                a[k] = v
        return a
    return _merge(_load(global_path, True), _load(user_path, False))

class SanhuaCmdShell(cmd.Cmd):
    """现代命令风格 CLI Shell，自动注册命令与动作，带链路DEBUG"""
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.intro = f"\n{EMOJI['star']} 三花聚顶交互控制台 v{__version__} {EMOJI['star']}"
        self.prompt = f"[{datetime.now().strftime('%H:%M:%S')}] 三花> "
        self._load_history()
        self._register_cmd_aliases()
        print(f"🧩 [DEBUG] 启动后已加载模块: {self.context.module_manager.list_all_modules() if self.context.module_manager else '无'}")
        print(f"🖇️ [DEBUG] 启动后可用动作: {list(self.context.list_actions())}")
        print(f"🛎️ [DEBUG] 已注册do_xxx命令: {[m for m in dir(self) if m.startswith('do_')]}")

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                readline.read_history_file(HISTORY_FILE)
                os.chmod(HISTORY_FILE, 0o600)
        except Exception as e:
            print(f"{EMOJI['warn']} 读取历史记录失败: {e}", file=sys.stderr)

    def _save_history(self):
        try:
            readline.set_history_length(MAX_HISTORY_LINES)
            readline.write_history_file(HISTORY_FILE)
            os.chmod(HISTORY_FILE, 0o600)
        except Exception as e:
            print(f"{EMOJI['warn']} 保存历史记录失败: {e}", file=sys.stderr)

    def _register_cmd_aliases(self):
        self.aliases = {
            'ls': 'list', 'modules': 'list', '?': 'help', 'quit': 'exit', 'ai': 'aicore', '智能': 'aicore'
        }

    # === 系统命令 ===
    def do_list(self, arg):
        mods = self.context.module_manager.list_all_modules() if self.context.module_manager else []
        if not mods:
            print(f"{EMOJI['warn']} 当前无已加载模块")
        else:
            print(f"{EMOJI['module']} 已加载模块：")
            for m in mods:
                print(f"- {m}")

    def do_help(self, arg):
        print(f"{EMOJI['star']} 可用命令/别名:")
        builtin = {name[3:] for name in dir(self) if name.startswith('do_')}
        for alias, cmd_ in self.aliases.items():
            print(f"  {alias:<10} (alias for {cmd_})")
        for c in sorted(builtin):
            print(f"  {c:<10} ")
        print("\n已注册动作:")
        for act in sorted(self.context.list_actions()):
            print(f"  {EMOJI['act']} {act}")

    def do_exit(self, arg):
        self._save_history()
        print(f"{EMOJI['exit']} 系统已安全退出，再见！")
        self.context.cleanup()
        return True

    def do_health(self, arg):
        res = self.context.module_manager.health_check() if self.context.module_manager else None
        if not isinstance(res, dict):
            print(f"{EMOJI['warn']} 健康检查异常：{res}")
            return
        print(f"{EMOJI['success']} 系统健康状态: {res.get('status', '未知')}")
        for mod, detail in res.get('modules', {}).items():
            st = detail.get('status', '未知')
            msg = detail.get('error', '') or ''
            print(f"  {mod:<18} : {st:<8} {msg}")
        if res.get('legacy_modules'):
            print("  [Legacy模块]:")
            for mod, detail in res.get('legacy_modules', {}).items():
                print(f"    {mod:<16}: {detail.get('status', 'UNKNOWN')}")
        print(f"  系统运行时长: {int(res.get('system_uptime', 0))} 秒")

    def do_reload(self, arg):
        try:
            result = self.context.module_manager.load_modules("cli")
            print(f"{EMOJI['ok']} 重载完成: {result}")
        except Exception as e:
            print(f"{EMOJI['fail']} 重载失败: {e}")

    def do_version(self, arg):
        print(f"三花聚顶 v{__version__}")

    def do_aicore(self, arg):
        """AI智能助手专用指令（如：aicore 你好、ai 推荐点音乐）"""
        q = arg.strip()
        if not q:
            print(f"{EMOJI['act']} 请输入AI问题，例如：aicore 你是谁")
            return

        try:
            from core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp import (
                ensure_ai_chat_actions_registered,
            )
            ensure_ai_chat_actions_registered()
        except Exception as e:
            print(f"{EMOJI['warn']} ai.chat 注册确保失败，将继续走兼容兜底: {e}")

        try:
            res = self.context.call_action(
                "ai.chat",
                params={"query": q, "prompt": q, "text": q, "message": q},
            )
            if isinstance(res, dict):
                data = res.get("data") or {}
                reply = data.get("reply") or res.get("reply") or res.get("response") or res.get("text")
            else:
                reply = res
            if reply:
                print(f"{EMOJI['act']} {reply}")
                return
        except Exception as e:
            print(f"{EMOJI['warn']} ai.chat 失败，转兼容兜底: {e}")

        try:
            res = self.context.call_action("aicore.chat", params={"query": q})
            if res:
                print(f"{EMOJI['act']} {res}")
                return
        except Exception as e:
            print(f"{EMOJI['warn']} aicore.chat 失败，转内部桥: {e}")

        if hasattr(self.context, "aicore"):
            try:
                res = self.context.aicore.chat(q)
                print(f"{EMOJI['act']} {res}")
                return
            except Exception as e:
                print(f"{EMOJI['fail']} AICore.chat 失败: {e}")
                return

        print(f"{EMOJI['fail']} 当前未集成AICore")

    # === 动作自动分发 ===
    def default(self, line):
        if not line.strip():
            return
        cmd_, *args = line.split()
        cmd_real = self.aliases.get(cmd_, cmd_)
        if hasattr(self, f"do_{cmd_real}"):
            return getattr(self, f"do_{cmd_real}")(' '.join(args))
        kwargs = {}
        for a in args:
            if "=" in a:
                k, v = a.split("=", 1)
                kwargs[k] = v
        try:
            res = self.context.call_action(cmd_real, params=kwargs)
            print(f"{EMOJI['ok']} {res}")
        except Exception as e:
            print(f"{EMOJI['fail']} 执行失败: {e}")

    def emptyline(self): pass

    def postcmd(self, stop, line):
        self.prompt = f"[{datetime.now().strftime('%H:%M:%S')}] 三花> "
        return stop

# ========== 主控核心：run 非阻塞版 ==========
def debug_run(self, entry_point: str = 'cli') -> None:
    if self._running:
        self.logger.warning("system_already_running")
        return
    try:
        print("🟡 [DEBUG] 1. 开始加载系统核心模块...")
        self.load_system_module()
        print("🟢 [DEBUG] 1.1 系统核心模块加载完成.")

        print("🟡 [DEBUG] 2. 读取全部模块元数据...")
        self.module_manager.load_modules_metadata()
        print(f"🟢 [DEBUG] 2.1 已发现模块: {list(self.module_manager.modules.keys())}")

        print(f"🟡 [DEBUG] 3. 按入口 {entry_point} 过滤/加载全部模块...")
        self.module_manager.load_modules(entry_point)
        print(f"🟢 [DEBUG] 3.1 当前已加载模块: {list(self.module_manager.loaded_modules.keys())}")

        with self._lock:
            if self._running:
                print("🟠 [WARN] 已经在运行，重复run跳过。")
                return
            self.context.system_running = True

            print("🟡 [DEBUG] 4. 启动所有已加载模块...")
            self.module_manager.start_modules()
            print("🟢 [DEBUG] 4.1 模块启动完成.")

            self._running = True
            self._shutting_down = False
            import threading
            self._health_report_thread = threading.Thread(
                target=self._health_report_loop,
                name="HealthReporter",
                daemon=True
            )
            self._health_report_thread.start()
        self.logger.info("system_started")
        print("🟢 [DEBUG] run()流程全部走完，CLI已可输入命令。")
    except Exception as e:
        self.logger.critical("system_run_failed", exc=e)
        print(f"🔴 [EXCEPTION] 主控run流程异常: {e}")
        self.shutdown()
        raise RuntimeError(f"系统启动失败: {str(e)}")

# ==== 主入口 ====
def main():
    PROJECT_ROOT, MODULES_DIR = find_project_root("modules", "经络")
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(MODULES_DIR))

    parser = argparse.ArgumentParser(
        description=f"三花聚顶 v{__version__}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--modules-dir", default=str(MODULES_DIR), help="功能模块目录")
    parser.add_argument("--global-config", default=str(Path(PROJECT_ROOT) / DEFAULT_CONFIG_DIR / "global.yaml"), help="全局配置")
    parser.add_argument("--user-config", default=str(Path(PROJECT_ROOT) / DEFAULT_CONFIG_DIR / "user.yaml"), help="用户配置")
    parser.add_argument("--entry", default="cli", choices=[x.value for x in AppMode], help="入口类型")
    parser.add_argument("--log-level", default="INFO", help="日志等级")
    parser.add_argument("--dev", action="store_true", help="开发模式")
    parser.add_argument("--version", action="store_true", help="显示版本")
    args = parser.parse_args()
    if args.version:
        print(f"三花聚顶 v{__version__}")
        sys.exit(0)

    banner = f"\n{EMOJI['star']} 三花聚顶 · CLI旗舰入口 {EMOJI['star']}"
    print(banner)
    print(f"根目录: {PROJECT_ROOT}\n模块目录: {MODULES_DIR}\n{'-'*40}")

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='[%(asctime)s] %(levelname)s %(message)s'
    )

    config = load_config(Path(args.global_config), Path(args.user_config))
    from core.core2_0.sanhuatongyu.master import SanHuaTongYu
    system = SanHuaTongYu(
        modules_dir=args.modules_dir,
        global_config_path=args.global_config,
        user_config_path=args.user_config,
        dev_mode=args.dev
    )
    system.run = debug_run.__get__(system)

    # CLI 直接复用 SystemContext 标准动作接口，不再覆盖到旧 ActionManager 总线
    if not hasattr(system.context, "call_action"):
        system.context.call_action = system.context.execute_action

    print(f"🖇️ [DEBUG] 启动前可用动作: {list(system.context.list_actions())}")
    if system.context.module_manager:
        print(f"🧩 [DEBUG] 启动前已加载模块: {system.context.module_manager.list_all_modules()}")

    def _handle_sig(signum, frame):
        print(f"\n{EMOJI['warn']} 收到信号 {signum}，准备退出...")
        system.shutdown()
        sys.exit(0)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, _handle_sig)

    try:
        system.run(entry_point=args.entry)
        if args.entry == "cli":
            SanhuaCmdShell(system.context).cmdloop()
        else:
            while system.is_running:
                time.sleep(2)
            print(f"{EMOJI['exit']} 系统服务已结束。")
    except Exception as e:
        print(f"{EMOJI['fail']} 主循环异常: {e}")
        try:
            system.shutdown()
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
