from __future__ import annotations

import logging
import os
import platform
import shutil
import time
from typing import Any, Dict, Optional

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class SystemMonitorModule:
    """
    三花聚顶 system_monitor 正式最小可用版
    目标：
    1. 提供 sysmon.status / sysmon.metrics / sysmon.health
    2. register_actions(dispatcher) 可直接被 bootstrap 调用
    3. entry 可被旧模块入口 import，不再炸包
    """

    name = "system_monitor"
    version = "2.0.0"
    title = "System Monitor Module"

    def __init__(self, *args, **kwargs):
        self.started = False

    def start(self) -> Dict[str, Any]:
        self.started = True
        return {
            "ok": True,
            "module": self.name,
            "status": "started",
        }

    def stop(self) -> Dict[str, Any]:
        self.started = False
        return {
            "ok": True,
            "module": self.name,
            "status": "stopped",
        }

    def health_check(self) -> Dict[str, Any]:
        snap = self._snapshot()
        return {
            "ok": True,
            "module": self.name,
            "source": "system_monitor_module",
            "started": self.started,
            "timestamp": snap["timestamp"],
            "platform": snap["platform"],
            "python": snap["python"],
        }

    def _snapshot(self) -> Dict[str, Any]:
        data = {
            "ok": True,
            "source": "system_monitor_module",
            "timestamp": int(time.time()),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cwd": os.getcwd(),
            "started": self.started,
        }

        try:
            du = shutil.disk_usage("/")
            data.update({
                "disk_total": int(du.total),
                "disk_used": int(du.used),
                "disk_free": int(du.free),
            })
        except Exception as e:
            data["disk_error"] = str(e)

        if psutil is not None:
            try:
                vm = psutil.virtual_memory()
                data.update({
                    "memory_total": int(vm.total),
                    "memory_used": int(vm.used),
                    "memory_available": int(vm.available),
                    "memory_percent": float(vm.percent),
                })
            except Exception as e:
                data["memory_error"] = str(e)

            try:
                data["cpu_percent"] = float(psutil.cpu_percent(interval=0.1))
            except Exception as e:
                data["cpu_error"] = str(e)
        else:
            data.update({
                "memory_total": None,
                "memory_used": None,
                "memory_available": None,
                "memory_percent": None,
                "cpu_percent": None,
            })

        return data

    # --------------------------------------------------------
    # dispatcher actions
    # --------------------------------------------------------

    def action_status(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        out = self._snapshot()
        out["view"] = "status"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_metrics(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        out = self._snapshot()
        out["view"] = "metrics"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_health(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        snap = self._snapshot()
        out = {
            "ok": True,
            "source": "system_monitor_module",
            "view": "health",
            "timestamp": snap["timestamp"],
            "platform": snap["platform"],
            "python": snap["python"],
            "started": self.started,
        }
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out


def get_module_instance(*args, **kwargs) -> SystemMonitorModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = SystemMonitorModule(*args, **kwargs)
    return _MODULE_SINGLETON


def _safe_unregister(dispatcher: Any, action_name: str) -> None:
    try:
        existing = dispatcher.get_action(action_name) if hasattr(dispatcher, "get_action") else None
    except Exception:
        existing = None

    if existing is not None and hasattr(dispatcher, "unregister_action"):
        try:
            dispatcher.unregister_action(action_name)
        except Exception:
            pass


def _safe_register(dispatcher: Any, action_name: str, func: Any) -> None:
    _safe_unregister(dispatcher, action_name)
    dispatcher.register_action(action_name, func)


def _safe_register_aliases(dispatcher: Any, action_name: str, aliases: list[str]) -> None:
    if not aliases:
        return

    if hasattr(dispatcher, "register_aliases"):
        try:
            dispatcher.register_aliases(action_name, aliases)
            return
        except TypeError:
            pass
        except Exception:
            pass

    if hasattr(dispatcher, "register_alias"):
        for alias in aliases:
            try:
                dispatcher.register_alias(alias, action_name)
                continue
            except TypeError:
                pass
            except Exception:
                pass

            try:
                dispatcher.register_alias(action_name, alias)
            except Exception:
                pass


def register_actions(dispatcher: Any) -> Dict[str, Any]:
    module = get_module_instance()

    _safe_register(dispatcher, "sysmon.status", module.action_status)
    _safe_register(dispatcher, "sysmon.metrics", module.action_metrics)
    _safe_register(dispatcher, "sysmon.health", module.action_health)

    def _register_bridge(action_name: str, func: Any) -> bool:
        try:
            existing = dispatcher.get_action(action_name) if hasattr(dispatcher, "get_action") else None
        except Exception:
            existing = None
        if existing is not None:
            return False
        _safe_register(dispatcher, action_name, func)
        return True

    _register_bridge("get_system_status", module.action_status)
    _register_bridge("get_system_metrics", module.action_metrics)

    _safe_register_aliases(
        dispatcher,
        "sysmon.status",
        [
            "系统状态",
            "查看系统状态",
            "监控状态",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "sysmon.metrics",
        [
            "系统指标",
            "监控指标",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "sysmon.health",
        [
            "系统健康",
            "监控健康",
        ],
    )

    log.info("system_monitor 动作注册完成: sysmon.status / sysmon.metrics / sysmon.health")
    return {
        "ok": True,
        "module": "system_monitor",
        "actions": ["sysmon.status", "sysmon.metrics", "sysmon.health"],
    }


def entry(*args, **kwargs) -> SystemMonitorModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "SystemMonitorModule",
    "get_module_instance",
    "register_actions",
    "entry",
]

# === SANHUA_OFFICIAL_WRAPPER_START ===
try:
    from core.core2_0.sanhuatongyu.module.base import BaseModule as _SanhuaBaseModule
except Exception:
    _SanhuaBaseModule = object


def _sanhua_safe_call(_fn, *args, **kwargs):
    if not callable(_fn):
        return None

    last_error = None

    trials = [
        lambda: _fn(*args, **kwargs),
        lambda: _fn(*args),
        lambda: _fn(),
    ]
    for call in trials:
        try:
            return call()
        except TypeError as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return None


class OfficialSystemMonitorModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for legacy module: system_monitor
    """

    def __init__(self, *args, **kwargs):
        context = kwargs.pop("context", None) if "context" in kwargs else None
        self.context = context
        self.dispatcher = kwargs.get("dispatcher")
        self.started = False

        try:
            super().__init__(*args, **kwargs)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass

        if self.context is None:
            self.context = context

    def _resolve_dispatcher(self, context=None):
        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            obj = getattr(self, name, None)
            if obj is not None:
                return obj

        if isinstance(context, dict):
            for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
                obj = context.get(name)
                if obj is not None:
                    return obj

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        return None

    def setup(self, context=None):
        if context is not None:
            self.context = context

        self.dispatcher = self._resolve_dispatcher(context or self.context)

        _register = globals().get("register_actions")
        if callable(_register) and self.dispatcher is not None:
            _sanhua_safe_call(_register, self.dispatcher)

        _legacy_setup = globals().get("setup")
        if callable(_legacy_setup):
            try:
                _sanhua_safe_call(_legacy_setup, context or self.context)
            except Exception:
                pass

        return {
            "ok": True,
            "module": "system_monitor",
            "view": "setup",
            "dispatcher_ready": self.dispatcher is not None,
            "legacy_wrapped": True,
        }

    def start(self):
        _legacy_start = globals().get("start")
        if callable(_legacy_start):
            try:
                _sanhua_safe_call(_legacy_start)
            except Exception:
                pass

        self.started = True
        return {
            "ok": True,
            "module": "system_monitor",
            "view": "start",
            "started": True,
        }

    def stop(self):
        _legacy_stop = globals().get("stop") or globals().get("shutdown")
        if callable(_legacy_stop):
            try:
                _sanhua_safe_call(_legacy_stop)
            except Exception:
                pass

        self.started = False
        return {
            "ok": True,
            "module": "system_monitor",
            "view": "stop",
            "started": False,
        }

    def health_check(self):
        _legacy_health = globals().get("health_check")
        if callable(_legacy_health):
            try:
                result = _sanhua_safe_call(_legacy_health)
                if isinstance(result, dict):
                    result.setdefault("ok", True)
                    result.setdefault("module", "system_monitor")
                    result.setdefault("view", "health_check")
                    return result
                return {
                    "ok": True,
                    "module": "system_monitor",
                    "view": "health_check",
                    "data": result,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "module": "system_monitor",
                    "view": "health_check",
                    "reason": str(e),
                }

        return {
            "ok": True,
            "module": "system_monitor",
            "view": "health_check",
            "started": self.started,
            "legacy_wrapped": True,
        }

    def preload(self):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 无需复杂预加载时，默认返回成功。
        """
        return {
            "ok": True,
            "module": "system_monitor",
            "view": "preload",
            "started": self.started,
            "wrapper": "OfficialSystemMonitorModule",
            "legacy_wrapped": True,
        }
    def handle_event(self, event_name, payload=None):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 默认不消费事件，返回 noop/ignored。
        """
        return {
            "ok": True,
            "module": "system_monitor",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "handled": False,
            "reason": "noop_legacy_wrapper",
            "wrapper": "OfficialSystemMonitorModule",
        }

def official_entry(context=None):
    _instance = OfficialSystemMonitorModule(context=context)
    _instance.setup(context=context)
    return _instance
# === SANHUA_OFFICIAL_WRAPPER_END ===
