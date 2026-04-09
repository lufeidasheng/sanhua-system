#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · desktop_notify（GNOME 桌面通知模块）
功能：标准动作/事件 → GNOME 通知；支持热插拔、健康检查、权限描述。
依赖：gi (libnotify)；Fedora/GNOME 优先，其他桌面会自动降级为控制台打印。
"""

from __future__ import annotations
# === SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1 START ===
import sys as _sanhua_dt_sys
import types as _sanhua_dt_types

if _sanhua_dt_sys.platform == "darwin":
    _fake_gi = _sanhua_dt_types.ModuleType("gi")

    def _sanhua_fake_require_version(*args, **kwargs):
        raise ImportError("gi disabled on darwin by SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1")

    _fake_gi.require_version = _sanhua_fake_require_version

    _fake_gi_repository = _sanhua_dt_types.ModuleType("gi.repository")
    _fake_gi.repository = _fake_gi_repository

    _sanhua_dt_sys.modules["gi"] = _fake_gi
    _sanhua_dt_sys.modules["gi.repository"] = _fake_gi_repository
# === SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1 END ===

import os
import time
from typing import Optional, Dict, Any

# === 三花聚顶基座 ===
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_MANAGER

log = get_logger("desktop_notify")

# --------- 可用性检测：libnotify ----------
_HAVE_LIBNOTIFY = False
Notify = None
try:
    import gi
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify
    _HAVE_LIBNOTIFY = True
except Exception as e:
    log.warning(f"libnotify 不可用，将降级为控制台输出: {e}")


# --------- 核心通知器 ----------
class _Notifier:
    """封装 GNOME 桌面通知；在无 libnotify 时降级为 print。"""
    _inited = False

    def __init__(self, app_name: str = "SanHuaJuDing"):
        self.app_name = app_name
        if _HAVE_LIBNOTIFY and not _Notifier._inited:
            try:
                Notify.init(self.app_name)
                _Notifier._inited = True
                log.info("libnotify 初始化成功")
            except Exception as e:
                log.warning(f"libnotify 初始化失败，降级为控制台输出: {e}")

    def send(self, title: str, body: str, icon: Optional[str] = None, timeout_ms: Optional[int] = None) -> bool:
        """发送系统通知；失败时返回 False。"""
        if _HAVE_LIBNOTIFY and _Notifier._inited:
            try:
                n = Notify.Notification.new(title or "通知", body or "", icon or "dialog-information")
                if timeout_ms is not None:
                    # 有的系统主题会忽略 timeout，这里尽量设置
                    n.set_timeout(timeout_ms)
                n.show()
                return True
            except Exception as e:
                log.error(f"发送 GNOME 通知失败: {e}")
                # 继续降级为控制台
        # 降级：打印
        print(f"[通知] {title}\n{body}\n")
        return False


# --------- 模块实现 ----------
class DesktopNotifyModule(BaseModule):
    VERSION = "1.0.0"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self._registered = False
        self._notifier = _Notifier(app_name="SanHuaJuDing Assistant")
        self._last_sent = 0.0
        log.info(f"{getattr(self.meta, 'name', 'desktop_notify')} v{self.VERSION} 初始化完成")

    # ========== 生命周期 ==========
    def preload(self):
        self._register_actions()
        # 订阅事件（若事件总线可用）
        if hasattr(self.context, "event_bus") and self.context.event_bus:
            self.context.event_bus.subscribe("notify.desktop", self.handle_event)
            self.context.event_bus.subscribe("notify.success", self.handle_event)
            self.context.event_bus.subscribe("notify.warning", self.handle_event)
            self.context.event_bus.subscribe("notify.error", self.handle_event)
        log.info("desktop_notify preload 完成")

    def setup(self):
        self._register_actions()
        log.info("desktop_notify setup 完成")

    def start(self):
        log.info("desktop_notify 启动完成")

    def stop(self):
        log.info("desktop_notify 停止")

    def cleanup(self):
        log.info("desktop_notify 清理完成")

    def health_check(self) -> Dict[str, Any]:
        status = "OK" if _HAVE_LIBNOTIFY and _Notifier._inited else "DEGRADED"
        reason = None if status == "OK" else "backend_stdout_fallback"
        return {
            "status": status,
            "reason": reason,
            "module": getattr(self.meta, "name", "desktop_notify"),
            "version": self.VERSION,
            "backend": "libnotify" if _HAVE_LIBNOTIFY and _Notifier._inited else "stdout",
            "last_sent": self._last_sent,
        }

    # ========== 事件处理 ==========
    def handle_event(self, event, *args, **kwargs):
        """
        统一事件入口：
        - 支持 event 为字符串（事件名）或对象（含 name/data）或 dict
        - 识别：notify.desktop / notify.success / notify.warning / notify.error
        data: {title, body, icon, timeout_ms}
        """
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

            level = "info"
            if name == "notify.success":
                level = "success"
            elif name == "notify.warning":
                level = "warning"
            elif name == "notify.error":
                level = "error"

            title = data.get("title") or self._title_for(level)
            body = data.get("body") or ""
            icon = data.get("icon") or self._icon_for(level)
            timeout_ms = data.get("timeout_ms")

            ok = self._send(title, body, icon, timeout_ms)

            # 回传完成事件（可选）
            if hasattr(self.context, "event_bus") and self.context.event_bus:
                self.context.event_bus.publish(
                    f"{name}.done",
                    {"ok": ok, "title": title, "body": body, "level": level}
                )
            return ok
        except Exception as e:
            log.error(f"handle_event 异常: {e}")
            return False

    # ========== 动作 ==========
    # 标准签名：context=None, params=None, **kwargs
    def action_desktop_notify(self, context=None, params=None, **kwargs) -> bool:
        params = params or {}
        title = params.get("title", "通知")
        body = params.get("body", "")
        icon = params.get("icon")  # e.g. "dialog-information"
        timeout_ms = params.get("timeout_ms")
        return self._send(title, body, icon, timeout_ms)

    def action_notify_success(self, context=None, params=None, **kwargs) -> bool:
        params = params or {}
        return self._send(
            params.get("title", self._title_for("success")),
            params.get("body", ""),
            params.get("icon", self._icon_for("success")),
            params.get("timeout_ms")
        )

    def action_notify_warning(self, context=None, params=None, **kwargs) -> bool:
        params = params or {}
        return self._send(
            params.get("title", self._title_for("warning")),
            params.get("body", ""),
            params.get("icon", self._icon_for("warning")),
            params.get("timeout_ms")
        )

    def action_notify_error(self, context=None, params=None, **kwargs) -> bool:
        params = params or {}
        return self._send(
            params.get("title", self._title_for("error")),
            params.get("body", ""),
            params.get("icon", self._icon_for("error")),
            params.get("timeout_ms")
        )

    # ========== 私有工具 ==========
    def _register_actions(self):
        if self._registered:
            return
        ACTION_MANAGER.register_action(
            name="desktop_notify",
            func=self.action_desktop_notify,
            description="发送桌面通知（GNOME/Libnotify）；params: {title, body, icon?, timeout_ms?}",
            permission="user",
            module="desktop_notify",
        )
        ACTION_MANAGER.register_action(
            name="notify.success",
            func=self.action_notify_success,
            description="发送成功通知；params: {title?, body, icon?, timeout_ms?}",
            permission="user",
            module="desktop_notify",
        )
        ACTION_MANAGER.register_action(
            name="notify.warning",
            func=self.action_notify_warning,
            description="发送警告通知；params: {title?, body, icon?, timeout_ms?}",
            permission="user",
            module="desktop_notify",
        )
        ACTION_MANAGER.register_action(
            name="notify.error",
            func=self.action_notify_error,
            description="发送错误通知；params: {title?, body, icon?, timeout_ms?}",
            permission="user",
            module="desktop_notify",
        )
        self._registered = True
        log.info("desktop_notify 动作已注册: ['desktop_notify', 'notify.success', 'notify.warning', 'notify.error']")

    def _send(self, title: str, body: str, icon: Optional[str], timeout_ms: Optional[int]) -> bool:
        self._last_sent = time.time()
        title = title or "通知"
        body = body or ""
        return self._notifier.send(title, body, icon, timeout_ms)

    @staticmethod
    def _title_for(level: str) -> str:
        return {
            "success": "✅ 成功",
            "warning": "⚠️ 警告",
            "error": "❌ 错误",
        }.get(level, "🔔 通知")

    @staticmethod
    def _icon_for(level: str) -> str:
        # 常见 GNOME 图标名称（主题相关）
        return {
            "success": "dialog-information",
            "warning": "dialog-warning",
            "error": "dialog-error",
        }.get(level, "dialog-information")


# ==== 热插拔脚手架（可被 ModuleManager 调用） ====
def register_actions(dispatcher, context=None):
    mod = DesktopNotifyModule(meta=getattr(dispatcher, "get_module_meta", lambda *_: None)("desktop_notify"), context=context)
    dispatcher.register_action(
        name="desktop_notify",
        func=mod.action_desktop_notify,
        description="发送桌面通知（GNOME/Libnotify）",
        permission="user",
        module="desktop_notify",
    )
    dispatcher.register_action(
        name="notify.success",
        func=mod.action_notify_success,
        description="发送成功通知",
        permission="user",
        module="desktop_notify",
    )
    dispatcher.register_action(
        name="notify.warning",
        func=mod.action_notify_warning,
        description="发送警告通知",
        permission="user",
        module="desktop_notify",
    )
    dispatcher.register_action(
        name="notify.error",
        func=mod.action_notify_error,
        description="发送错误通知",
        permission="user",
        module="desktop_notify",
    )
    log.info("register_actions: desktop_notify 动作注册完成")


# ==== 内嵌元数据（如未使用外置 manifest.json，可让主控发现） ====
MODULE_METADATA = {
    "name": "desktop_notify",
    "version": DesktopNotifyModule.VERSION,
    "description": "GNOME 桌面通知模块：动作/事件转系统通知；支持降级输出。",
    "author": "三花聚顶开发团队",
    "entry": "modules.desktop_notify",
    "actions": [
        {"name": "desktop_notify", "description": "发送桌面通知", "permission": "user"},
        {"name": "notify.success", "description": "发送成功通知", "permission": "user"},
        {"name": "notify.warning", "description": "发送警告通知", "permission": "user"},
        {"name": "notify.error", "description": "发送错误通知", "permission": "user"},
    ],
    "dependencies": ["gi"],
    "config_schema": {},
}

MODULE_CLASS = DesktopNotifyModule


# === SANHUA_DESKTOP_NOTIFY_DARWIN_MONKEYPATCH_V2 START ===
def _sanhua_dt_is_darwin():
    try:
        import sys
        return sys.platform == "darwin"
    except Exception:
        return False


def _sanhua_dt_log(level: str, message: str):
    for _name in ("logger", "log", "LOGGER", "_logger"):
        _obj = globals().get(_name)
        if _obj is not None and hasattr(_obj, level):
            try:
                getattr(_obj, level)(message)
                return
            except Exception:
                pass
    try:
        print(message)
    except Exception:
        pass


def _sanhua_dt_console_notify(title: str, message: str):
    try:
        print(f"[desktop_notify:fallback] {title}: {message}")
    except Exception:
        pass
    return {
        "ok": True,
        "backend": "console_fallback",
        "title": title,
        "message": message,
    }


def _sanhua_dt_notify_macos(title: str, message: str):
    try:
        import subprocess

        safe_title = str(title).replace('"', '\\"')
        safe_message = str(message).replace('"', '\\"')
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], check=False)
        return {
            "ok": True,
            "backend": "macos_osascript",
            "title": title,
            "message": message,
        }
    except Exception:
        return _sanhua_dt_console_notify(title, message)


def _sanhua_dt_extract_title_message(args, kwargs):
    title = kwargs.get("title")
    message = kwargs.get("message")

    if title is None and len(args) >= 1:
        title = args[0]
    if message is None and len(args) >= 2:
        message = args[1]

    if title is None:
        title = "三花聚顶"
    if message is None:
        if len(args) == 1 and "title" not in kwargs:
            message = str(args[0])
            title = "三花聚顶"
        else:
            message = ""

    return str(title), str(message)


def _sanhua_dt_install_darwin_patch():
    if not _sanhua_dt_is_darwin():
        return

    _cls = globals().get("DesktopNotifyModule")
    if not isinstance(_cls, type):
        _sanhua_dt_log("warning", "desktop_notify: 未找到 DesktopNotifyModule，跳过 Darwin monkey patch")
        return

    def _sanhua_dt_backend_bootstrap(self, *args, **kwargs):
        try:
            self._notify_backend = "macos_osascript"
            self.notify_backend = "macos_osascript"
            self._notify_impl = _sanhua_dt_notify_macos
        except Exception:
            pass
        return {
            "ok": True,
            "backend": "macos_osascript",
            "reason": "darwin_monkey_patch",
        }

    def _sanhua_dt_send(self, *args, **kwargs):
        title, message = _sanhua_dt_extract_title_message(args, kwargs)
        return _sanhua_dt_notify_macos(title, message)

    # 1) 覆盖常见初始化方法，阻断 gi/libnotify 链路
    for _name in (
        "_init_notify_backend",
        "init_notify_backend",
        "_setup_notify_backend",
        "setup_notify_backend",
        "_init_notifier",
        "init_notifier",
        "_init_notify",
        "init_notify",
        "_ensure_notify_backend",
        "ensure_notify_backend",
    ):
        try:
            setattr(_cls, _name, _sanhua_dt_backend_bootstrap)
        except Exception:
            pass

    # 2) 覆盖 setup，避免 setup 内继续触发 gi/libnotify
    try:
        setattr(_cls, "setup", _sanhua_dt_backend_bootstrap)
    except Exception:
        pass

    # 3) 覆盖常见通知发送方法
    for _name in (
        "notify",
        "_notify",
        "send_notification",
        "_send_notification",
        "show_notification",
        "_show_notification",
        "push_notification",
        "_push_notification",
    ):
        try:
            setattr(_cls, _name, _sanhua_dt_send)
        except Exception:
            pass

    _sanhua_dt_log("info", "desktop_notify: Darwin monkey patch active (osascript/console fallback)")

try:
    _sanhua_dt_install_darwin_patch()
except Exception as _e:
    try:
        print(f"desktop_notify: Darwin monkey patch install failed: {_e}")
    except Exception:
        pass
# === SANHUA_DESKTOP_NOTIFY_DARWIN_MONKEYPATCH_V2 END ===
