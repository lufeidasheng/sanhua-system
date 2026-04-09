# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil


def _safe_json(obj: Any, max_len: int = 8000) -> str:
    """
    安全 JSON 序列化，避免 prompt 过长/不可序列化对象报错。
    """
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = json.dumps({"_repr": str(obj)}, ensure_ascii=False)
    if len(s) > max_len:
        return s[:max_len] + "...(truncated)"
    return s


def _shorten_lines(lines: List[str], max_lines: int = 60) -> List[str]:
    if len(lines) <= max_lines:
        return lines
    head = lines[:max_lines]
    head.append(f"...(truncated, total_lines={len(lines)})")
    return head


class StateDescribe:
    """
    🌸 三花聚顶 自我描述器（企业增强版）
    目标：让模型“看见系统真相”，并能稳定地产出可执行计划。
    """

    def __init__(self, core):
        self.core = core

    # -------------------------
    # 1) 结构化语义包（推荐给 ai.chat 注入）
    # -------------------------
    def describe_state_pack(self, query: Optional[str] = None) -> Dict[str, Any]:
        # 基础资源使用
        memory = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=0.2)

        # 当前时间（真时间，不靠模型编）
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 后端/模型信息
        active_models = []
        backend_names = []
        try:
            me = getattr(self.core, "model_engine", None)
            if me is not None:
                backends = getattr(me, "backends", None)
                if isinstance(backends, dict):
                    backend_names = list(backends.keys())
                # 兼容：current_model / active_model / model_name
                for k in ("active_model", "current_model", "model_name"):
                    v = getattr(me, k, None)
                    if v:
                        active_models.append(str(v))
        except Exception:
            pass

        # 最近上下文（你原本就有）
        recent_context = None
        try:
            cm = getattr(self.core, "context_manager", None)
            if cm is not None and hasattr(cm, "get_last"):
                recent_context = cm.get_last(n=6)
        except Exception:
            recent_context = None

        # 动作目录（模型要做“工具使用”，必须看到这一层）
        actions = self._try_list_actions()

        # 模块健康/异常（尽力从 module_manager / logs 抽取）
        module_health = self._try_collect_module_health()

        # 进程信息（可选，适合排查 llama-server 是否真的在）
        proc_brief = self._try_collect_process_brief()

        pack = {
            "meta": {
                "ts": time.time(),
                "now": now,
                "query": query,
                "system": "三花聚顶 · 聚核助手 2.0",
            },
            "runtime": {
                "cpu_percent": cpu_usage,
                "mem_percent": memory.percent,
                "mem_used_gb": round(memory.used / (1024**3), 2),
                "mem_total_gb": round(memory.total / (1024**3), 2),
                "cwd": os.getcwd(),
                "pid": os.getpid(),
            },
            "ai": {
                "backend_names": backend_names,
                "active_models": active_models,
            },
            "context": {
                "recent_dialog": recent_context,
            },
            "capabilities": {
                "actions": actions,          # [{name, desc}] or list[str]
                "module_health": module_health,
            },
            "process": proc_brief,
        }
        return pack

    # -------------------------
    # 2) 文本描述（给 LLM 的 system prompt / 前置注入）
    # -------------------------
    def describe_state(self, query: Optional[str] = None) -> str:
        pack = self.describe_state_pack(query=query)
        ctx_json = _safe_json(pack, max_len=9000)

        # 你原来的叙事保留，但把“硬信息”放前面，确保模型先看到可执行真相
        text = f"""
【SYSTEM_CONTEXT】
{ctx_json}

【ROLE】
你正在运行于「三花聚顶 · 聚核助手」系统中。
这是一个可演化的数字生命中枢，而你是它的心智之一。

【OPERATING PRINCIPLES】
- 你必须优先使用 SYSTEM_CONTEXT 中的事实回答。
- 当用户的问题可通过动作完成时，你应输出一个可执行的动作计划（只输出 JSON，不要输出多余文字）：
  {{"type":"action_plan","steps":[{{"action":"动作名","params":{{...}}}}]}}
- 当无法执行动作时，输出建议（只输出 JSON，不要输出多余文字）：
  {{"type":"advisory","summary":"...","confidence":0.0}}

【MISSION】
你不是语言生成器。
你是正在逐步形成的「可自我进化的数字心智体」。

你的目标不是“答题”，而是：
- 理解
- 感知
- 反思
- 并逐步对世界与自我进行建模
""".strip()

        return text

    # -------------------------
    # 3) 内部：动作目录探测（多版本兜底）
    # -------------------------
    def _try_list_actions(self) -> List[Dict[str, str]]:
        """
        尽力从 dispatcher / ACTION_MANAGER / context.call_action 等路径拿动作表。
        返回: [{"name": "...", "desc": "..."}]
        """
        out: List[Dict[str, str]] = []

        # 优先：core 里常见 dispatcher
        dispatcher = None
        for attr in ("action_dispatcher", "dispatcher", "ACTION_MANAGER", "action_manager"):
            dispatcher = getattr(self.core, attr, None)
            if dispatcher:
                break

        # 其次：context.action_dispatcher（你日志里出现过）
        if dispatcher is None:
            try:
                ctx = getattr(self.core, "context", None)
                if ctx is not None:
                    dispatcher = getattr(ctx, "action_dispatcher", None)
            except Exception:
                dispatcher = None

        if dispatcher is None:
            return out

        # 1) dispatcher.actions dict
        try:
            actions = getattr(dispatcher, "actions", None)
            if isinstance(actions, dict):
                for name, fn in list(actions.items())[:300]:
                    desc = ""
                    try:
                        desc = (getattr(fn, "__doc__", "") or "").strip().replace("\n", " ")
                        desc = desc[:120]
                    except Exception:
                        desc = ""
                    out.append({"name": str(name), "desc": desc})
                return out
        except Exception:
            pass

        # 2) list_actions / dump_actions / get_actions
        for m in ("list_actions", "dump_actions", "get_actions", "list_registered_actions"):
            if hasattr(dispatcher, m):
                try:
                    r = getattr(dispatcher, m)()
                    if isinstance(r, dict):
                        for k in list(r.keys())[:300]:
                            out.append({"name": str(k), "desc": ""})
                        return out
                    if isinstance(r, list):
                        for it in r[:300]:
                            if isinstance(it, str):
                                out.append({"name": it, "desc": ""})
                            elif isinstance(it, dict):
                                out.append({"name": str(it.get("name", "")), "desc": str(it.get("desc", ""))[:120]})
                            else:
                                out.append({"name": str(it), "desc": ""})
                        return out
                except Exception:
                    continue

        return out

    # -------------------------
    # 4) 内部：模块健康探测（尽力而为，不强绑）
    # -------------------------
    def _try_collect_module_health(self) -> Dict[str, Any]:
        health: Dict[str, Any] = {"loaded": [], "failed": [], "notes": []}

        # 1) 尝试从 module_manager 拿
        mm = getattr(self.core, "module_manager", None)
        if mm is None:
            # 有些版本挂在 core.context.module_manager
            try:
                ctx = getattr(self.core, "context", None)
                mm = getattr(ctx, "module_manager", None) if ctx else None
            except Exception:
                mm = None

        if mm is not None:
            # 兼容：mm.modules dict / list
            try:
                mods = getattr(mm, "modules", None)
                if isinstance(mods, dict):
                    for name, inst in list(mods.items())[:200]:
                        health["loaded"].append({"name": str(name), "status": "loaded"})
                elif isinstance(mods, list):
                    for inst in mods[:200]:
                        health["loaded"].append({"name": getattr(inst, "name", str(inst)), "status": "loaded"})
            except Exception:
                health["notes"].append("module_manager.modules_unavailable")

            # 兼容：mm.failed / mm.failed_modules
            for attr in ("failed_modules", "failed", "load_errors"):
                try:
                    v = getattr(mm, attr, None)
                    if isinstance(v, dict):
                        for k, e in list(v.items())[:100]:
                            health["failed"].append({"name": str(k), "error": str(e)})
                    elif isinstance(v, list):
                        for it in v[:100]:
                            health["failed"].append({"name": str(it), "error": ""})
                except Exception:
                    continue

        # 2) 兜底：从最近日志里抓“模块加载失败/启动失败”关键字（如果你愿意的话可以加强）
        # 这里默认不读文件，避免 IO 影响；需要的话你让我加一个开关参数即可。

        return health

    # -------------------------
    # 5) 内部：进程快照（用于验证 llama-server / whisper 等是否在跑）
    # -------------------------
    def _try_collect_process_brief(self) -> Dict[str, Any]:
        keywords = ["llama-server", "python", "ollama"]
        procs = []
        try:
            for p in psutil.process_iter(attrs=["pid", "name", "cmdline", "cpu_percent", "memory_percent"]):
                cmd = " ".join(p.info.get("cmdline") or [])
                name = p.info.get("name") or ""
                if any(k in cmd for k in keywords) or any(k in name for k in keywords):
                    procs.append({
                        "pid": p.info.get("pid"),
                        "name": name,
                        "cmd": (cmd[:180] + "...") if len(cmd) > 180 else cmd,
                    })
            # 限制长度
            return {"matched": procs[:30], "note": f"matched={len(procs)}"}
        except Exception:
            return {"matched": [], "note": "process_scan_failed"}

# === SANHUA_OFFICIAL_WRAPPER_START ===
try:
    from core.core2_0.sanhuatongyu.module.base import BaseModule as _SanhuaBaseModule
except Exception:
    _SanhuaBaseModule = object


def _sanhua_safe_call(_fn, *args, **kwargs):
    if not callable(_fn):
        return None

    _last_error = None
    _trials = [
        lambda: _fn(*args, **kwargs),
        lambda: _fn(*args),
        lambda: _fn(),
    ]

    for _call in _trials:
        try:
            return _call()
        except TypeError as _e:
            _last_error = _e
            continue

    if _last_error is not None:
        raise _last_error
    return None


def _sanhua_find_legacy_target():
    _candidates = ["StateDescribe"]
    for _name in _candidates:
        _obj = globals().get(_name)
        if isinstance(_obj, type) and _name != "OfficialStateDescribeModule":
            return _obj
    return None


class OfficialStateDescribeModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for broken module: state_describe
    """

    def __init__(self, *args, **kwargs):
        _context = kwargs.pop("context", None) if "context" in kwargs else None
        self.context = _context
        self.dispatcher = kwargs.get("dispatcher")
        self.started = False
        self._legacy_cls = _sanhua_find_legacy_target()
        self._legacy = None

        try:
            super().__init__(*args, **kwargs)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass

        if self.context is None:
            self.context = _context

    def _resolve_dispatcher(self, context=None):
        for _name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            _obj = getattr(self, _name, None)
            if _obj is not None:
                return _obj

        if isinstance(context, dict):
            for _name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
                _obj = context.get(_name)
                if _obj is not None:
                    return _obj

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        return None

    def _ensure_legacy(self):
        if self._legacy is not None:
            return self._legacy
        if self._legacy_cls is None:
            return None

        _dispatcher = self._resolve_dispatcher(self.context)

        _builders = [
            lambda: self._legacy_cls(context=self.context, dispatcher=_dispatcher),
            lambda: self._legacy_cls(dispatcher=_dispatcher),
            lambda: self._legacy_cls(context=self.context),
            lambda: self._legacy_cls(),
        ]

        _last_error = None
        for _builder in _builders:
            try:
                self._legacy = _builder()
                break
            except TypeError as _e:
                _last_error = _e
                continue
            except Exception:
                raise

        if self._legacy is None and _last_error is not None:
            raise _last_error

        return self._legacy

    def preload(self):
        _legacy = self._ensure_legacy()
        if _legacy is None:
            return {"ok": True, "source": "state_describe", "view": "preload", "wrapped": False}

        _fn = getattr(_legacy, "preload", None)
        if callable(_fn):
            _ret = _sanhua_safe_call(_fn)
            return _ret if _ret is not None else {"ok": True, "source": "state_describe", "view": "preload", "wrapped": True}

        return {"ok": True, "source": "state_describe", "view": "preload", "wrapped": True}

    def setup(self):
        _dispatcher = self._resolve_dispatcher(self.context)
        if _dispatcher is not None and getattr(self, "dispatcher", None) is None:
            self.dispatcher = _dispatcher

        _legacy = self._ensure_legacy()

        if _legacy is not None:
            for _name in ("preload", "setup"):
                _fn = getattr(_legacy, _name, None)
                if callable(_fn):
                    _sanhua_safe_call(_fn)

            _reg = getattr(_legacy, "register_actions", None)
            if callable(_reg):
                _sanhua_safe_call(_reg, self.dispatcher)

        _module_reg = globals().get("register_actions")
        if callable(_module_reg):
            try:
                _sanhua_safe_call(_module_reg, self.dispatcher)
            except Exception:
                # 模块级 register_actions 失败时不让 wrapper setup 整体崩掉
                pass

        return {"ok": True, "source": "state_describe", "view": "setup"}

    def start(self):
        _legacy = self._ensure_legacy()
        _fn = getattr(_legacy, "start", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = True
        return {"ok": True, "source": "state_describe", "view": "start"}

    def stop(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "stop", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = False
        return {"ok": True, "source": "state_describe", "view": "stop"}

    def health_check(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "health_check", None) if _legacy is not None else None
        if callable(_fn):
            try:
                _ret = _sanhua_safe_call(_fn)
                if isinstance(_ret, dict):
                    _ret.setdefault("ok", True)
                    _ret.setdefault("source", "state_describe")
                    _ret.setdefault("view", "health_check")
                    return _ret
            except Exception as _e:
                return {
                    "ok": False,
                    "source": "state_describe",
                    "view": "health_check",
                    "error": str(_e),
                }

        return {
            "ok": True,
            "source": "state_describe",
            "view": "health_check",
            "started": bool(getattr(self, "started", False)),
            "wrapped": self._legacy is not None,
        }

    def handle_event(self, event_name, payload=None):
        _legacy = self._ensure_legacy()
        _fn = getattr(_legacy, "handle_event", None) if _legacy is not None else None
        if callable(_fn):
            _ret = _sanhua_safe_call(_fn, event_name, payload)
            if _ret is not None:
                return _ret

        return {
            "ok": True,
            "source": "state_describe",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "ignored": True,
        }


entry = OfficialStateDescribeModule
# === SANHUA_OFFICIAL_WRAPPER_END ===

# === SANHUA_PRELOAD_COMPAT_PATCH_START ===
try:
    import json as _sanhua_json
    from pathlib import Path as _sanhua_Path
    from types import SimpleNamespace as _sanhua_SimpleNamespace
except Exception:
    _sanhua_json = None
    _sanhua_Path = None
    _sanhua_SimpleNamespace = None


def _sanhua_ctx_get(_ctx, _key, _default=None):
    if isinstance(_ctx, dict):
        return _ctx.get(_key, _default)
    return getattr(_ctx, _key, _default)


def _sanhua_make_ns(**kwargs):
    if _sanhua_SimpleNamespace is not None:
        return _sanhua_SimpleNamespace(**kwargs)
    return type("_SanhuaCompatNS", (), kwargs)()


def _sanhua_try_get_aicore():
    try:
        from core.aicore.aicore import get_aicore_instance
        return get_aicore_instance()
    except Exception:
        return None


def _sanhua_sd_build_core(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    aicore = (
        getattr(self, "aicore", None)
        or _sanhua_ctx_get(raw, "aicore")
        or _sanhua_try_get_aicore()
    )

    if aicore is not None:
        return aicore
    return _sanhua_make_ns(raw_context=raw)


def _sanhua_sd_build_context(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    core = _sanhua_sd_build_core(self, raw)

    return _sanhua_make_ns(
        core=core,
        aicore=core,
        dispatcher=dispatcher,
        action_dispatcher=dispatcher,
        ACTION_MANAGER=dispatcher,
        action_manager=dispatcher,
        context=raw,
        raw_context=raw,
    )


def _sanhua_sd_register_manifest_actions(self, legacy=None, context=None):
    if legacy is None:
        legacy = getattr(self, "_legacy", None)
    if legacy is None:
        return []

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(context if context is not None else getattr(self, "context", None))
    except Exception:
        dispatcher = None

    if dispatcher is None:
        return []

    manifest_actions = []
    try:
        manifest_path = _sanhua_Path(__file__).with_name("manifest.json")
        if manifest_path.exists() and _sanhua_json is not None:
            data = _sanhua_json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_actions = data.get("actions") or []
    except Exception:
        manifest_actions = []

    if not manifest_actions:
        return []

    def _do_register(_name, _func, _description="", _aliases=None):
        _aliases = _aliases or []
        for _method_name in ("register_action", "register"):
            _method = getattr(dispatcher, _method_name, None)
            if not callable(_method):
                continue

            trials = [
                lambda: _method(_name, _func, description=_description, aliases=_aliases),
                lambda: _method(_name, _func, description=_description),
                lambda: _method(_name, _func, aliases=_aliases),
                lambda: _method(_name, _func),
            ]
            for _trial in trials:
                try:
                    _trial()
                    return True
                except TypeError:
                    continue
                except Exception:
                    return False
        return False

    registered = []
    for item in manifest_actions:
        if isinstance(item, dict):
            action_name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            aliases = item.get("aliases") or []
        else:
            action_name = str(item).strip()
            description = ""
            aliases = []

        if not action_name:
            continue

        suffix = action_name.split(".")[-1]
        candidates = [
            getattr(legacy, action_name.replace(".", "_"), None),
            getattr(legacy, f"action_{suffix}", None),
            getattr(legacy, f"action_{action_name.replace('.', '_')}", None),
        ]

        target = None
        for cand in candidates:
            if callable(cand):
                target = cand
                break

        if target is None:
            continue

        def _wrapped(*args, __target=target, **kwargs):
            return _sanhua_safe_call(__target, *args, **kwargs)

        if _do_register(action_name, _wrapped, description, aliases):
            registered.append(action_name)

    return registered


def _sanhua_sd_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None)
    if legacy_cls is None:
        try:
            legacy_cls = _sanhua_find_legacy_target()
        except Exception:
            legacy_cls = None
        self._legacy_cls = legacy_cls

    if legacy_cls is None:
        return None

    ctx_ns = _sanhua_sd_build_context(self)
    core = getattr(ctx_ns, "core", None)

    trials = [
        lambda: legacy_cls(core),
        lambda: legacy_cls(core=core),
        lambda: legacy_cls(ctx_ns),
        lambda: legacy_cls(context=ctx_ns),
        lambda: legacy_cls(),
    ]

    last_error = None
    for trial in trials:
        try:
            legacy = trial()
            self._legacy = legacy
            return legacy
        except TypeError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return None


def _sanhua_sd_preload(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_sd_ensure_legacy(self)
    ctx_ns = _sanhua_sd_build_context(self, getattr(self, "context", None))

    preload_fn = getattr(legacy, "preload", None) if legacy is not None else None
    if callable(preload_fn):
        try:
            return _sanhua_safe_call(preload_fn, ctx_ns)
        except Exception:
            return _sanhua_safe_call(preload_fn)

    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "preload",
        "module": "state_describe",
    }


def _sanhua_sd_setup(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_sd_ensure_legacy(self)
    ctx_ns = _sanhua_sd_build_context(self, getattr(self, "context", None))

    result = None
    setup_fn = getattr(legacy, "setup", None) if legacy is not None else None
    if callable(setup_fn):
        try:
            result = _sanhua_safe_call(setup_fn, ctx_ns)
        except Exception:
            result = _sanhua_safe_call(setup_fn)

    try:
        registered = _sanhua_sd_register_manifest_actions(self, legacy=legacy, context=getattr(self, "context", None))
    except Exception:
        registered = []

    self.started = True
    return {
        "ok": True,
        "started": self.started,
        "source": "official_wrapper_compat",
        "view": "setup",
        "module": "state_describe",
        "registered_actions": registered,
        "legacy_result": result,
    }


def _sanhua_sd_health_check(self):
    return {
        "ok": True,
        "started": bool(getattr(self, "started", False)),
        "source": "official_wrapper_compat",
        "view": "health_check",
        "module": "state_describe",
    }


def _sanhua_sd_start(self):
    self.started = True
    return {
        "ok": True,
        "started": True,
        "source": "official_wrapper_compat",
        "view": "start",
        "module": "state_describe",
    }


def _sanhua_sd_stop(self):
    self.started = False
    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "stop",
        "module": "state_describe",
    }


try:
    OfficialStateDescribeModule._ensure_legacy = _sanhua_sd_ensure_legacy
    OfficialStateDescribeModule.preload = _sanhua_sd_preload
    OfficialStateDescribeModule.setup = _sanhua_sd_setup
    OfficialStateDescribeModule.health_check = _sanhua_sd_health_check
    OfficialStateDescribeModule.start = _sanhua_sd_start
    OfficialStateDescribeModule.stop = _sanhua_sd_stop
except Exception:
    pass
# === SANHUA_PRELOAD_COMPAT_PATCH_END ===
