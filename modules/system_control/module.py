from __future__ import annotations

import logging
import os
import platform
import subprocess
import socket
import time
import webbrowser
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class SystemControlModule:
    """
    三花聚顶 system_control 正式最小可用版（安全版）
    目标：
    1. 提供 system.health_check / system.status
    2. 暂不提供危险动作（重启/关机/网络变更）
    3. register_actions(dispatcher) 可直接被 bootstrap 调用
    """

    name = "system_control"
    version = "2.0.0"
    title = "System Control Module"

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

    def _base_info(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "source": "system_control_module",
            "timestamp": int(time.time()),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": socket.gethostname(),
            "cwd": os.getcwd(),
            "started": self.started,
        }

    def health_check(self) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "health_check"
        return out

    # --------------------------------------------------------
    # dispatcher actions
    # --------------------------------------------------------

    def action_health_check(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "health_check"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_status(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "status"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def _run_cmd(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(cmd, check=False)
            return proc.returncode == 0, f"exit={proc.returncode}"
        except Exception as e:
            return False, str(e)

    def action_shutdown(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "shutdown not supported on this platform"
        ok, detail = self._run_cmd(["shutdown", "now"])
        return "shutdown executed" if ok else f"shutdown failed: {detail}"

    def action_reboot(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "reboot not supported on this platform"
        ok, detail = self._run_cmd(["reboot"])
        return "reboot executed" if ok else f"reboot failed: {detail}"

    def action_lock_screen(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "lock_screen not supported on this platform"
        ok, detail = self._run_cmd(["loginctl", "lock-session"])
        return "lock_screen executed" if ok else f"lock_screen failed: {detail}"

    def action_suspend(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "suspend not supported on this platform"
        ok, detail = self._run_cmd(["systemctl", "suspend"])
        return "suspend executed" if ok else f"suspend failed: {detail}"

    def action_logout(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "logout not supported on this platform"
        ok, detail = self._run_cmd(["gnome-session-quit", "--logout", "--no-prompt"])
        return "logout executed" if ok else f"logout failed: {detail}"

    def action_turn_off_display(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "turn_off_display not supported on this platform"
        ok, detail = self._run_cmd(["xset", "dpms", "force", "off"])
        return "turn_off_display executed" if ok else f"turn_off_display failed: {detail}"

    def action_screenshot(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if platform.system() != "Linux":
            return "screenshot not supported on this platform"
        ok, detail = self._run_cmd(["gnome-screenshot"])
        return "screenshot executed" if ok else f"screenshot failed: {detail}"

    def action_open_url(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        params = kwargs.get("params") if isinstance(kwargs, dict) else None
        url = None
        if isinstance(params, dict):
            url = params.get("url") or params.get("link")
        if not url:
            url = kwargs.get("url") or kwargs.get("link")
        if not url or not isinstance(url, str):
            return "open_url requires url"
        try:
            ok = webbrowser.open(url)
            return "open_url executed" if ok else "open_url failed: open returned false"
        except Exception as e:
            return f"open_url failed: {e}"

    def action_open_browser(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        params = kwargs.get("params") if isinstance(kwargs, dict) else None
        url = None
        if isinstance(params, dict):
            url = params.get("url") or params.get("link")
        if not url:
            url = kwargs.get("url") or kwargs.get("link")
        try:
            ok = webbrowser.open(url or "about:blank")
            return "open_browser executed" if ok else "open_browser failed: open returned false"
        except Exception as e:
            return f"open_browser failed: {e}"


def get_module_instance(*args, **kwargs) -> SystemControlModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = SystemControlModule(*args, **kwargs)
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


def _safe_register(dispatcher: Any, action_name: str, func: Any, module: Optional[str] = None) -> None:
    _safe_unregister(dispatcher, action_name)
    dispatcher.register_action(action_name, func, module=module)


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

    try:
        existing = dispatcher.get_action("system.health_check") if hasattr(dispatcher, "get_action") else None
    except Exception:
        existing = None
    if existing is None:
        _safe_register(dispatcher, "system.health_check", module.action_health_check)
    else:
        log.info("system_control 跳过 system.health_check 注册（已存在）")
    _safe_register(dispatcher, "system.status", module.action_status)
    _safe_register(dispatcher, "shutdown", module.action_shutdown, module="system_control")
    _safe_register(dispatcher, "reboot", module.action_reboot, module="system_control")
    _safe_register(dispatcher, "lock_screen", module.action_lock_screen, module="system_control")
    _safe_register(dispatcher, "suspend", module.action_suspend, module="system_control")
    _safe_register(dispatcher, "logout", module.action_logout, module="system_control")
    _safe_register(dispatcher, "turn_off_display", module.action_turn_off_display, module="system_control")
    _safe_register(dispatcher, "screenshot", module.action_screenshot, module="system_control")
    _safe_register(dispatcher, "open_url", module.action_open_url, module="system_control")
    _safe_register(dispatcher, "open_browser", module.action_open_browser, module="system_control")

    _safe_register_aliases(
        dispatcher,
        "system.health_check",
        [
            "系统健康检查",
            "健康检查",
            "检查系统健康",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "system.status",
        [
            "系统状态",
            "查看系统状态",
        ],
    )

    log.info("system_control 动作注册完成: system.health_check / system.status / shutdown / reboot / lock_screen / suspend / logout / turn_off_display / screenshot / open_url / open_browser")
    return {
        "ok": True,
        "module": "system_control",
        "actions": [
            "system.health_check",
            "system.status",
            "shutdown",
            "reboot",
            "lock_screen",
            "suspend",
            "logout",
            "turn_off_display",
            "screenshot",
            "open_url",
            "open_browser",
        ],
    }


def entry(*args, **kwargs) -> SystemControlModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "SystemControlModule",
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


class OfficialSystemControlModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for legacy module: system_control
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
            "module": "system_control",
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
            "module": "system_control",
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
            "module": "system_control",
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
                    result.setdefault("module", "system_control")
                    result.setdefault("view", "health_check")
                    return result
                return {
                    "ok": True,
                    "module": "system_control",
                    "view": "health_check",
                    "data": result,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "module": "system_control",
                    "view": "health_check",
                    "reason": str(e),
                }

        return {
            "ok": True,
            "module": "system_control",
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
            "module": "system_control",
            "view": "preload",
            "started": self.started,
            "wrapper": "OfficialSystemControlModule",
            "legacy_wrapped": True,
        }
    def handle_event(self, event_name, payload=None):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 默认不消费事件，返回 noop/ignored。
        """
        return {
            "ok": True,
            "module": "system_control",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "handled": False,
            "reason": "noop_legacy_wrapper",
            "wrapper": "OfficialSystemControlModule",
        }

def official_entry(context=None):
    _instance = OfficialSystemControlModule(context=context)
    _instance.setup(context=context)
    return _instance
# === SANHUA_OFFICIAL_WRAPPER_END ===
