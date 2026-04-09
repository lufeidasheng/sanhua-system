# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any

from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as dispatcher
from core.core2_0.sanhuatongyu.events import get_event_bus
from core.core2_0.sanhuatongyu.services.model_engine.engine import ModelEngine


class ModelEngineActionsModule:
    """
    🌸 模型引擎动作模块
    """

    def __init__(self, context):
        self.ctx = context
        # 🔥 从 AICore 拿实际模型引擎实例
        self.engine: ModelEngine = _sanhua_resolve_model_engine_from_context(context)
        self.bus = get_event_bus()

    # ---------------- 生命周期 ----------------
    def preload(self): pass
    def setup(self): self._register_actions()
    def start(self): pass
    def stop(self): pass
    def cleanup(self): pass

    # ---------------- Action 注册 ----------------
    def _register_actions(self):
        _sanhua_dispatcher_register_action(dispatcher, "model.list", self.action_list_models, module_name="model_engine_actions")
        _sanhua_dispatcher_register_action(dispatcher, "model.select", self.action_select_model, module_name="model_engine_actions")
        _sanhua_dispatcher_register_action(dispatcher, "model.current", self.action_current_model, module_name="model_engine_actions")

    # ---------------- Action 实现 ----------------
    def action_list_models(self, params: Dict[str, Any]):
        """列出可用模型"""
        models = self.engine.list_local_models()
        if not models:
            return "⚠️ models 目录中没有可用模型 (.gguf / .bin)"
        return models

    def action_select_model(self, params: Dict[str, Any]):
        """切换模型"""
        name = params.get("name")
        if not name:
            return "❌ 缺少参数: name=\"模型文件名\""

        try:
            self.engine.select_model(name)
            # ✅ 切换后广播事件 → GUI 可监听刷新
            self.bus.emit("model.changed", {"name": name})
            return f"✅ 已切换模型：{name}"

        except Exception as e:
            return f"❌ 切换失败: {e}"

    def action_current_model(self, params: Dict[str, Any]):
        """显示当前模型"""
        return self.engine.active_model_path or "（当前未选择）"

# === SANHUA_MODEL_ENGINE_COMPAT_START ===
class _SanhuaNullModelEngine:
    """
    当 AICore 上没有标准 model_engine 属性时的降级兼容对象。
    目标：
    - 让 model_engine_actions 至少能 preload/setup 通过
    - current_model / list_models 之类动作可安全返回
    - 不阻塞 GUI 主启动链
    """

    def __init__(self):
        self.active_model_path = None
        self.available_models = []
        self.degraded = True
        self.reason = "aicore.model_engine_missing"

    def list_models(self):
        return list(self.available_models)

    def current_model(self):
        return self.active_model_path

    def get_current_model(self):
        return self.active_model_path

    def set_active_model(self, model_path):
        self.active_model_path = model_path
        if model_path and model_path not in self.available_models:
            self.available_models.append(model_path)
        return True

    def switch_model(self, model_path):
        return self.set_active_model(model_path)

    def ensure_ready(self):
        return True

    def health_check(self):
        return {
            "ok": True,
            "degraded": True,
            "reason": self.reason,
            "active_model_path": self.active_model_path,
            "available_models": list(self.available_models),
        }

    def __getattr__(self, name):
        def _fallback(*args, **kwargs):
            return {
                "ok": False,
                "reason": f"null_model_engine_method_not_available:{name}",
                "name": name,
            }
        return _fallback


def _sanhua_me_getattr_any(obj, *names):
    if obj is None:
        return None

    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj.get(name) is not None:
                return obj.get(name)
        return None

    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return None


def _sanhua_resolve_model_engine_from_context(context):
    """
    按多条路径解析模型引擎：
    1. context.aicore.model_engine
    2. context.aicore 的替代引擎字段
    3. context 本身携带的替代引擎字段
    4. 全局 get_aicore_instance()
    5. 最终返回 _SanhuaNullModelEngine
    """
    engine_field_candidates = (
        "model_engine",
        "_model_engine",
        "llm_engine",
        "engine",
        "model_manager",
        "inference_engine",
        "backend_engine",
    )

    aicore = _sanhua_me_getattr_any(context, "aicore")
    if aicore is not None:
        engine = _sanhua_me_getattr_any(aicore, *engine_field_candidates)
        if engine is not None:
            try:
                if getattr(aicore, "model_engine", None) is None:
                    setattr(aicore, "model_engine", engine)
            except Exception:
                pass
            return engine

    engine = _sanhua_me_getattr_any(context, *engine_field_candidates)
    if engine is not None:
        return engine

    try:
        from core.aicore.aicore import get_aicore_instance
        ai = get_aicore_instance()
    except Exception:
        ai = None

    if ai is not None:
        engine = _sanhua_me_getattr_any(ai, *engine_field_candidates)
        if engine is not None:
            try:
                if getattr(ai, "model_engine", None) is None:
                    setattr(ai, "model_engine", engine)
            except Exception:
                pass
            return engine

    return _SanhuaNullModelEngine()

# === SANHUA_MODEL_ENGINE_COMPAT_END ===

# === SANHUA_MODEL_ENGINE_DISPATCHER_COMPAT_START ===

def _sanhua_dispatcher_register_action(dispatcher, action_name, func, **kwargs):
    """
    兼容不同版本 dispatcher.register_action / register 的签名差异。
    目标：
    - 允许 legacy 模块继续声明 module_name / description / aliases
    - 避免因为旧签名参数导致 setup 直接炸掉
    """
    if dispatcher is None:
        raise RuntimeError("dispatcher is None")

    errors = []

    register_fn = getattr(dispatcher, "register_action", None)
    if callable(register_fn):
        trials = [
            lambda: register_fn(action_name, func, **kwargs),
            lambda: register_fn(action_name, func),
            lambda: register_fn(name=action_name, func=func, **kwargs),
            lambda: register_fn(name=action_name, func=func),
            lambda: register_fn(name=action_name, action=func, **kwargs),
            lambda: register_fn(name=action_name, action=func),
        ]
        for trial in trials:
            try:
                return trial()
            except TypeError as e:
                errors.append(e)
            except Exception:
                raise

    register_fn = getattr(dispatcher, "register", None)
    if callable(register_fn):
        trials = [
            lambda: register_fn(action_name, func, **kwargs),
            lambda: register_fn(action_name, func),
            lambda: register_fn(name=action_name, func=func, **kwargs),
            lambda: register_fn(name=action_name, func=func),
            lambda: register_fn(name=action_name, action=func, **kwargs),
            lambda: register_fn(name=action_name, action=func),
        ]
        for trial in trials:
            try:
                return trial()
            except TypeError as e:
                errors.append(e)
            except Exception:
                raise

    if errors:
        raise errors[-1]
    raise RuntimeError("dispatcher has no register_action/register method")


def _sanhua_mea_is_event_bus_not_ready_error(exc: Exception) -> bool:
    text = str(exc or "")
    return ("事件总线未初始化" in text) or ("init_event_bus" in text)


def _sanhua_mea_register_actions_direct(self, legacy):
    """
    当 legacy.setup() 因 dispatcher 签名不兼容失败时，直接兜底注册核心动作。
    """
    ctx = getattr(self, "context", None)
    dispatcher = None

    if hasattr(self, "_resolve_dispatcher"):
        try:
            dispatcher = self._resolve_dispatcher(ctx)
        except Exception:
            dispatcher = None

    if dispatcher is None:
        dispatcher = getattr(self, "dispatcher", None)

    if dispatcher is None:
        raise RuntimeError("model_engine_actions: dispatcher unavailable")

    registered = []

    candidates = [
        ("model.list", "action_list_models"),
        ("model.switch", "action_switch_model"),
        ("model.current", "action_current_model"),
    ]

    for action_name, method_name in candidates:
        fn = getattr(legacy, method_name, None)
        if callable(fn):
            _sanhua_dispatcher_register_action(
                dispatcher,
                action_name,
                fn,
                module_name="model_engine_actions",
            )
            registered.append(action_name)

    return {
        "ok": True,
        "registered": registered,
        "count": len(registered),
        "mode": "direct_register_fallback",
    }


def _sanhua_mea_preload_runtime_compat(self):
    legacy = _sanhua_mea_ensure_legacy(self)
    preload_fn = getattr(legacy, "preload", None)
    if not callable(preload_fn):
        self._sanhua_preload_degraded = False
        self._sanhua_preload_reason = "no_preload"
        return {"ok": True, "reason": "no_preload"}

    ctx_ns = None
    build_ctx = globals().get("_sanhua_mea_build_context_ns")
    if callable(build_ctx):
        try:
            ctx_ns = build_ctx(self)
        except Exception:
            ctx_ns = getattr(self, "context", None)
    else:
        ctx_ns = getattr(self, "context", None)

    try:
        result = _sanhua_safe_call(preload_fn, ctx_ns)
        self._sanhua_preload_degraded = False
        self._sanhua_preload_reason = None
        return result
    except Exception as e:
        if _sanhua_mea_is_event_bus_not_ready_error(e):
            self._sanhua_preload_degraded = True
            self._sanhua_preload_reason = str(e)
            return {
                "ok": True,
                "degraded": True,
                "reason": str(e),
            }
        raise


def _sanhua_mea_setup_runtime_compat(self):
    legacy = _sanhua_mea_ensure_legacy(self)
    setup_fn = getattr(legacy, "setup", None)

    if not callable(setup_fn):
        fallback = _sanhua_mea_register_actions_direct(self, legacy)
        self._sanhua_setup_mode = "direct_register_fallback"
        return fallback

    ctx_ns = None
    build_ctx = globals().get("_sanhua_mea_build_context_ns")
    if callable(build_ctx):
        try:
            ctx_ns = build_ctx(self)
        except Exception:
            ctx_ns = getattr(self, "context", None)
    else:
        ctx_ns = getattr(self, "context", None)

    try:
        result = _sanhua_safe_call(setup_fn, ctx_ns)
        self._sanhua_setup_mode = "legacy_setup"
        return result
    except Exception as e:
        text = str(e or "")
        if ("register_action() got an unexpected keyword argument" in text) or ("module_name" in text):
            fallback = _sanhua_mea_register_actions_direct(self, legacy)
            self._sanhua_setup_mode = "direct_register_fallback"
            return fallback
        raise


def _sanhua_mea_health_check_runtime_compat(self):
    return {
        "ok": True,
        "module": "model_engine_actions",
        "degraded": bool(getattr(self, "_sanhua_preload_degraded", False)),
        "preload_reason": getattr(self, "_sanhua_preload_reason", None),
        "setup_mode": getattr(self, "_sanhua_setup_mode", None),
    }


try:
    OfficialModelEngineActionsModule.preload = _sanhua_mea_preload_runtime_compat_runtime_compat
    OfficialModelEngineActionsModule.setup = _sanhua_mea_setup_runtime_compat_runtime_compat
    OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check_runtime_compat_runtime_compat
except Exception:
    pass

# === SANHUA_MODEL_ENGINE_DISPATCHER_COMPAT_END ===

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
    _candidates = ["ModelEngineActionsModule"]
    for _name in _candidates:
        _obj = globals().get(_name)
        if isinstance(_obj, type) and _name != "OfficialModelEngineActionsModule":
            return _obj
    return None


class OfficialModelEngineActionsModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for broken module: model_engine_actions
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
            return {"ok": True, "source": "model_engine_actions", "view": "preload", "wrapped": False}

        _fn = getattr(_legacy, "preload", None)
        if callable(_fn):
            _ret = _sanhua_safe_call(_fn)
            return _ret if _ret is not None else {"ok": True, "source": "model_engine_actions", "view": "preload", "wrapped": True}

        return {"ok": True, "source": "model_engine_actions", "view": "preload", "wrapped": True}

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

        return {"ok": True, "source": "model_engine_actions", "view": "setup"}

    def start(self):
        _legacy = self._ensure_legacy()
        _fn = getattr(_legacy, "start", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = True
        return {"ok": True, "source": "model_engine_actions", "view": "start"}

    def stop(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "stop", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = False
        return {"ok": True, "source": "model_engine_actions", "view": "stop"}

    def health_check(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "health_check", None) if _legacy is not None else None
        if callable(_fn):
            try:
                _ret = _sanhua_safe_call(_fn)
                if isinstance(_ret, dict):
                    _ret.setdefault("ok", True)
                    _ret.setdefault("source", "model_engine_actions")
                    _ret.setdefault("view", "health_check")
                    return _ret
            except Exception as _e:
                return {
                    "ok": False,
                    "source": "model_engine_actions",
                    "view": "health_check",
                    "error": str(_e),
                }

        return {
            "ok": True,
            "source": "model_engine_actions",
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
            "source": "model_engine_actions",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "ignored": True,
        }


entry = OfficialModelEngineActionsModule
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


def _sanhua_mea_build_legacy_context(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    aicore = (
        getattr(self, "aicore", None)
        or _sanhua_ctx_get(raw, "aicore")
        or _sanhua_try_get_aicore()
    )

    return _sanhua_make_ns(
        aicore=aicore,
        dispatcher=dispatcher,
        action_dispatcher=dispatcher,
        ACTION_MANAGER=dispatcher,
        action_manager=dispatcher,
        context=raw,
        raw_context=raw,
    )


def _sanhua_mea_register_manifest_actions(self, legacy=None, context=None):
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



def _sanhua_mea_get_global_aicore():
    try:
        from core.aicore.aicore import get_aicore_instance
        ai = get_aicore_instance()
        if ai is not None:
            return ai
    except Exception:
        pass
    return None


def _sanhua_mea_resolve_dispatcher_from_any(obj):
    if obj is None:
        return None

    names = ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager")

    if isinstance(obj, dict):
        for name in names:
            val = obj.get(name)
            if val is not None:
                return val
        return None

    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return None


def _sanhua_mea_resolve_aicore_from_any(obj):
    if obj is None:
        return None

    if isinstance(obj, dict):
        return obj.get("aicore")

    try:
        val = getattr(obj, "aicore", None)
        if val is not None:
            return val
    except Exception:
        pass

    return None


def _sanhua_mea_build_context_proxy(self):
    from types import SimpleNamespace

    raw = getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    if dispatcher is None:
        dispatcher = _sanhua_mea_resolve_dispatcher_from_any(raw)

    if dispatcher is None:
        dispatcher = getattr(self, "dispatcher", None)

    aicore = getattr(self, "aicore", None)
    if aicore is None:
        aicore = _sanhua_mea_resolve_aicore_from_any(raw)

    if aicore is None:
        aicore = _sanhua_mea_get_global_aicore()

    data = {}

    if isinstance(raw, dict):
        data.update(raw)
    elif raw is not None:
        for name in (
            "aicore",
            "dispatcher",
            "action_dispatcher",
            "ACTION_MANAGER",
            "action_manager",
            "root",
            "project_root",
            "config",
            "settings",
            "memory_manager",
            "prompt_memory_bridge",
        ):
            try:
                if hasattr(raw, name):
                    data[name] = getattr(raw, name)
            except Exception:
                pass

    if aicore is not None:
        data["aicore"] = aicore

    if dispatcher is not None:
        data["dispatcher"] = dispatcher
        data["action_dispatcher"] = dispatcher
        data["ACTION_MANAGER"] = dispatcher
        data["action_manager"] = dispatcher

    root_val = str(getattr(self, "root", "") or "") or data.get("root") or ""
    data.setdefault("root", root_val)
    data.setdefault("project_root", root_val)

    return SimpleNamespace(**data)


def _sanhua_mea_context_candidates(self):
    from types import SimpleNamespace

    raw = getattr(self, "context", None)
    proxy = _sanhua_mea_build_context_proxy(self)

    out = [proxy]

    if raw is not None:
        out.append(raw)

    mini = SimpleNamespace(
        aicore=getattr(proxy, "aicore", None),
        dispatcher=getattr(proxy, "dispatcher", None),
        action_dispatcher=getattr(proxy, "action_dispatcher", None),
        ACTION_MANAGER=getattr(proxy, "ACTION_MANAGER", None),
        action_manager=getattr(proxy, "action_manager", None),
        root=getattr(proxy, "root", ""),
        project_root=getattr(proxy, "project_root", ""),
    )
    out.append(mini)

    return out


def _sanhua_mea_instantiate_legacy(legacy_cls, ctx):
    import inspect

    last_error = None

    try:
        init_sig = inspect.signature(legacy_cls.__init__)
        params = [p for p in init_sig.parameters.values() if p.name != "self"]
    except Exception:
        params = []

    has_context_kw = any(p.name == "context" for p in params)
    has_dispatcher_kw = any(p.name == "dispatcher" for p in params)
    allow_positional = bool(params)

    dispatcher = _sanhua_mea_resolve_dispatcher_from_any(ctx)

    trials = []

    if has_context_kw and has_dispatcher_kw:
        trials.append(lambda: legacy_cls(context=ctx, dispatcher=dispatcher))

    if has_context_kw:
        trials.append(lambda: legacy_cls(context=ctx))

    if allow_positional:
        trials.append(lambda: legacy_cls(ctx))

    if has_dispatcher_kw:
        trials.append(lambda: legacy_cls(context=ctx, dispatcher=None))

    # 注意：这里故意不再保留 legacy_cls() 无参兜底
    for trial in trials:
        try:
            return trial()
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError("legacy instantiate failed: no usable constructor path")


def _sanhua_mea_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None) or _sanhua_find_legacy_target()
    if legacy_cls is None:
        self._legacy = None
        return None

    last_error = None

    for ctx in _sanhua_mea_context_candidates(self):
        try:
            legacy = _sanhua_mea_instantiate_legacy(legacy_cls, ctx)
            self._legacy = legacy
            return legacy
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError("legacy init failed: no context candidate worked")


def _sanhua_mea_preload(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_mea_ensure_legacy(self)
    ctx_ns = _sanhua_mea_build_legacy_context(self, getattr(self, "context", None))

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
        "module": "model_engine_actions",
    }


def _sanhua_mea_setup(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_mea_ensure_legacy(self)
    ctx_ns = _sanhua_mea_build_legacy_context(self, getattr(self, "context", None))

    result = None
    setup_fn = getattr(legacy, "setup", None) if legacy is not None else None
    if callable(setup_fn):
        try:
            result = _sanhua_safe_call(setup_fn, ctx_ns)
        except Exception:
            result = _sanhua_safe_call(setup_fn)

    try:
        registered = _sanhua_mea_register_manifest_actions(self, legacy=legacy, context=getattr(self, "context", None))
    except Exception:
        registered = []

    self.started = True
    return {
        "ok": True,
        "started": self.started,
        "source": "official_wrapper_compat",
        "view": "setup",
        "module": "model_engine_actions",
        "registered_actions": registered,
        "legacy_result": result,
    }


def _sanhua_mea_health_check(self):
    return {
        "ok": True,
        "started": bool(getattr(self, "started", False)),
        "source": "official_wrapper_compat",
        "view": "health_check",
        "module": "model_engine_actions",
    }


def _sanhua_mea_start(self):
    self.started = True
    return {
        "ok": True,
        "started": True,
        "source": "official_wrapper_compat",
        "view": "start",
        "module": "model_engine_actions",
    }


def _sanhua_mea_stop(self):
    self.started = False
    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "stop",
        "module": "model_engine_actions",
    }


try:
    OfficialModelEngineActionsModule._ensure_legacy = _sanhua_mea_ensure_legacy
    OfficialModelEngineActionsModule.preload = _sanhua_mea_preload_runtime_compat
    OfficialModelEngineActionsModule.setup = _sanhua_mea_setup_runtime_compat
    OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check_runtime_compat
    OfficialModelEngineActionsModule.start = _sanhua_mea_start
    OfficialModelEngineActionsModule.stop = _sanhua_mea_stop
except Exception:
    pass
# === SANHUA_PRELOAD_COMPAT_PATCH_END ===
