#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · VirtualAvatarModule（企业级演示/虚拟形象入口）
- 既可作为“功能模块”装载进平台，也可被 GUI 直接驱动
- 事件驱动：根据系统/业务事件触发动画与表情
- GUI对接：通过 ui_bridge 调用前端播放动画（无前端时自动降级为日志）
- 动作齐备：virtual_avatar.start/show/stop/play/pose/say/health/switch
- 兼容别名：avatar.*（与旧版/脚本保持一致）
"""

from __future__ import annotations
import os
import time
import asyncio
import logging
from typing import Dict, Optional, Callable, Any

# === 框架基座 ===
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

log = get_logger("virtual_avatar")
IS_FEDORA = os.path.exists("/etc/fedora-release")

# ---------------- 元信息（供模块管理器读取） ----------------
__metadata__ = {
    "id": "virtual_avatar",
    "name": "virtual_avatar",  # ⚠ manifest/模块名一致
    "version": "1.1.0",
    "entry_class": "modules.virtual_avatar.module.VirtualAvatarModule",
    "enabled": True,
    "entry_points": ["core", "gui"],
    "events": [
        "system_shutdown", "user_command", "performance_alert",
        "fedora_update", "avatar.say", "avatar.react"
    ],
    "dependencies": [],
    "actions": [
        {"name": "virtual_avatar.start", "permission": "user"},
        {"name": "virtual_avatar.show", "permission": "user"},
        {"name": "virtual_avatar.stop", "permission": "user"},
        {"name": "virtual_avatar.play", "permission": "user"},
        {"name": "virtual_avatar.pose", "permission": "user"},
        {"name": "virtual_avatar.say", "permission": "user"},
        {"name": "virtual_avatar.health", "permission": "user"},
        {"name": "virtual_avatar.switch", "permission": "admin"}
    ],
}

# ---------------- 默认动画表（前端资源需自行提供） ----------------
COMMON_ANIM = {
    "boot": "fade_in",
    "show": "fade_in",
    "shutdown": "fade_out",
    "thinking": "pulse",
    "speaking": "talk_loop",
    "success": "success_burst",
    "warning": "warning_glow",
    "error": "shake",
    "idle": "idle_breath",
    "wave": "wave_hand",
}

FEDORA_ANIM_EXTRA = {
    "boot": "fedora_spin",
    "update": "rpm_install",
    "secure": "selinux_lock",
    "optimize": "pipewave",
}

def _merge_anim():
    anim = dict(COMMON_ANIM)
    if IS_FEDORA:
        anim.update(FEDORA_ANIM_EXTRA)
    return anim

# ---------------- GUI 桥（与前端解耦，找不到则降级为日志） ----------------
class UIBridge:
    def __init__(self, ctx):
        # 约定：context.ui_bridge 可注入回调：play_animation, set_expression, show_toast, set_avatar, set_visible
        ub = getattr(ctx, "ui_bridge", None) if ctx else None
        self.play_animation: Optional[Callable[..., Any]] = getattr(ub, "play_animation", None) if ub else None
        self.set_expression: Optional[Callable[..., Any]] = getattr(ub, "set_expression", None) if ub else None
        self.show_toast: Optional[Callable[..., Any]] = getattr(ub, "show_toast", None) if ub else None
        self.set_avatar: Optional[Callable[..., Any]] = getattr(ub, "set_avatar", None) if ub else None
        self.set_visible: Optional[Callable[..., Any]] = getattr(ub, "set_visible", None) if ub else None

    def play(self, name: str, **kw):
        if self.play_animation:
            try:
                return self.play_animation(name=name, **kw)
            except Exception as e:
                log.warning(f"[UIBridge] play_animation 失败: {e}")
        log.info(f"[Avatar] 播放动画（降级日志）：{name}  参数={kw}")

    def expression(self, expr: str, **kw):
        if self.set_expression:
            try:
                return self.set_expression(expr=expr, **kw)
            except Exception as e:
                log.warning(f"[UIBridge] set_expression 失败: {e}")
        log.info(f"[Avatar] 表情（降级日志）：{expr}")

    def toast(self, msg: str, level="info", **kw):
        if self.show_toast:
            try:
                return self.show_toast(message=msg, level=level, **kw)
            except Exception as e:
                log.warning(f"[UIBridge] show_toast 失败: {e}")
        log.info(f"[Avatar][{level}] {msg}")

    def switch_avatar(self, avatar_id: str):
        if self.set_avatar:
            try:
                return self.set_avatar(avatar_id=avatar_id)
            except Exception as e:
                log.warning(f"[UIBridge] set_avatar 失败: {e}")
        log.info(f"[Avatar] 切换形象（降级日志）：{avatar_id}")

    def visible(self, show: bool = True):
        if self.set_visible:
            try:
                return self.set_visible(visible=show)
            except Exception as e:
                log.warning(f"[UIBridge] set_visible 失败: {e}")
        log.info(f"[Avatar] 可见性（降级日志）：{show}")

# ---------------- 模块实现 ----------------
class VirtualAvatarModule(BaseModule):
    VERSION = "1.1.0"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.config: Dict[str, Any] = getattr(meta, "config", {}) if meta else {}
        self.ui = UIBridge(context)
        self.anim = _merge_anim()
        self.avatar_id = self.config.get("avatar_id", "default")
        self.started_at = 0.0
        self._visible = False
        log.info(f"[avatar] 初始化完成（avatar_id={self.avatar_id} fedora={IS_FEDORA}）")

    # ---- 生命周期 ----
    def preload(self):
        # 订阅事件总线（若存在）
        bus = getattr(self.context, "event_bus", None)
        if bus:
            for ev in __metadata__["events"]:
                bus.subscribe(ev, self.handle_event)
        # 注册动作
        self._register_actions()
        log.info("[avatar] preload 完成，事件/动作已注册")

    def setup(self):
        # 预热动画或表情（可选）
        self.ui.switch_avatar(self.avatar_id)
        log.info("[avatar] setup 完成")

    def start(self):
        self.started_at = time.time()
        self.ui.visible(True)
        self._visible = True
        self.ui.toast("虚拟形象已就绪", level="info")
        self.ui.play(self.anim.get("boot", "fade_in"))

    def stop(self):
        self.ui.play(self.anim.get("shutdown", "fade_out"))
        self.ui.toast("虚拟形象已停止", level="info")
        self.ui.visible(False)
        self._visible = False

    def cleanup(self):
        log.info("[avatar] cleanup 完成")

    # ---- 健康检查（供系统聚合）----
    def health_check(self) -> Dict[str, Any]:
        uptime = time.time() - self.started_at if self.started_at else 0
        return {
            "status": "OK",
            "module": "virtual_avatar",
            "version": self.VERSION,
            "avatar_id": self.avatar_id,
            "uptime": uptime,
            "fedora": IS_FEDORA,
            "visible": self._visible,
            "has_ui_callbacks": {
                "play_animation": bool(self.ui.play_animation),
                "set_expression": bool(self.ui.set_expression),
                "show_toast": bool(self.ui.show_toast),
                "set_avatar": bool(self.ui.set_avatar),
                "set_visible": bool(self.ui.set_visible),
            },
        }

    # ---- 抽象方法实现：事件入口 ----
    def handle_event(self, event, *args, **kwargs):
        """符合 BaseModule 抽象要求的事件处理器"""
        try:
            if hasattr(event, "name"):
                name = event.name
                data = event.data or {}
            elif isinstance(event, dict):
                name = event.get("name", "")
                data = event.get("data", {}) or {}
            else:
                name = str(event or "")
                data = kwargs.get("data", {}) or {}

            # 核心映射
            if name == "system_shutdown":
                self.ui.toast("系统即将关闭", level="warning")
                self.ui.play(self.anim.get("shutdown", "fade_out"))
                self.ui.visible(False)
                self._visible = False
                return True

            if name == "performance_alert":
                typ = data.get("alert_type", "generic")
                self.ui.toast(f"性能警报：{typ}", level="warning")
                self.ui.play(self.anim.get("warning", "warning_glow"))
                return True

            if name == "fedora_update" and IS_FEDORA:
                ver = data.get("version", "unknown")
                self.ui.toast(f"Fedora 更新：{ver}", level="info")
                self.ui.play(self.anim.get("update", "rpm_install"))
                return True

            if name == "avatar.say":
                # data: { "text": "...", "mood": "happy|sad|neutral" }
                txt = data.get("text", "")
                mood = data.get("mood", "neutral")
                if txt:
                    self.ui.toast(txt, level="info")
                self.ui.expression(mood)
                self.ui.play(self.anim.get("speaking", "talk_loop"))
                return True

            if name == "avatar.react":
                # data: { "type": "success|warning|error|wave|idle" }
                t = (data.get("type") or "").lower()
                key = {
                    "success": "success",
                    "warning": "warning",
                    "error": "error",
                    "wave": "wave",
                    "idle": "idle",
                }.get(t, "idle")
                self.ui.play(self.anim.get(key, "idle_breath"))
                return True

            if name == "user_command":
                cmd = (data.get("command") or "").lower()
                if cmd == "module_status":
                    self.ui.toast("虚拟形象状态良好", level="info")
                    self.ui.play(self.anim.get("thinking", "pulse"))
                    return True

            log.debug(f"[avatar] 未处理事件：{name}")
            return False
        except Exception as e:
            log.error(f"[avatar] 事件处理异常：{e}")
            return {"error": str(e)}

    # ---- 动作：供 GUI/别名/脚本调用 ----
    def action_va_start(self, context=None, params=None, **kwargs):
        """virtual_avatar.start：显示并播放开场动画"""
        p = params or {}
        aid = p.get("avatar_id")
        if aid:
            self.avatar_id = aid
            self.ui.switch_avatar(aid)
        self.ui.visible(True)
        self._visible = True
        self.ui.play(self.anim.get("boot", "fade_in"))
        self.ui.toast("虚拟形象启动", level="info")
        return {"status": "ok", "visible": True, "avatar_id": self.avatar_id}

    def action_va_show(self, context=None, params=None, **kwargs):
        """virtual_avatar.show：仅显示（不重置状态）"""
        self.ui.visible(True)
        self._visible = True
        self.ui.play(self.anim.get("show", "fade_in"))
        return {"status": "ok", "visible": True}

    def action_va_stop(self, context=None, params=None, **kwargs):
        """virtual_avatar.stop：播放关场动画并隐藏"""
        self.ui.play(self.anim.get("shutdown", "fade_out"))
        self.ui.visible(False)
        self._visible = False
        return {"status": "ok", "visible": False}

    def action_avatar_play(self, context=None, params=None, **kwargs):
        """virtual_avatar.play：播放指定动画"""
        p = params or {}
        name = p.get("name")
        if not name:
            return {"status": "error", "msg": "缺少动画名称 name"}
        self.ui.play(name, loop=bool(p.get("loop", False)), speed=float(p.get("speed", 1.0)))
        return {"status": "ok"}

    def action_avatar_pose(self, context=None, params=None, **kwargs):
        """virtual_avatar.pose：设置表情/姿态"""
        p = params or {}
        expr = p.get("expression", "neutral")
        self.ui.expression(expr)
        return {"status": "ok"}

    def action_avatar_say(self, context=None, params=None, **kwargs):
        """virtual_avatar.say：说一句（并触发表情/说话动画）"""
        p = params or {}
        txt = p.get("text", "")
        mood = p.get("mood", "neutral")
        if txt:
            self.ui.toast(txt, level="info")
        self.ui.expression(mood)
        self.ui.play(self.anim.get("speaking", "talk_loop"))
        return {"status": "ok"}

    def action_avatar_health(self, context=None, params=None, **kwargs):
        return self.health_check()

    def action_avatar_switch(self, context=None, params=None, **kwargs):
        """virtual_avatar.switch：切换虚拟形象"""
        p = params or {}
        aid = p.get("avatar_id") or "default"
        self.avatar_id = aid
        self.ui.switch_avatar(aid)
        return {"status": "ok", "avatar_id": aid}

    # ---- 注册动作（含兼容别名）----
    def _register_actions(self):
        # 新标准前缀
        ACTION_DISPATCHER.register_action("virtual_avatar.start",  self.action_va_start,  description="启动虚拟形象", permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.show",   self.action_va_show,   description="显示虚拟形象", permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.stop",   self.action_va_stop,   description="停止并隐藏",   permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.play",   self.action_avatar_play,  description="播放动画",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.pose",   self.action_avatar_pose,  description="设置表情",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.say",    self.action_avatar_say,   description="说一句并联动", permission="user", module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.health", self.action_avatar_health, description="健康状态",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("virtual_avatar.switch", self.action_avatar_switch, description="切换形象",  permission="admin", module="virtual_avatar")

        # 兼容旧前缀 avatar.*
        ACTION_DISPATCHER.register_action("avatar.start",  self.action_va_start,  description="[兼容] 启动虚拟形象", permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.show",   self.action_va_show,   description="[兼容] 显示虚拟形象", permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.stop",   self.action_va_stop,   description="[兼容] 停止并隐藏",   permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.play",   self.action_avatar_play,  description="[兼容] 播放动画",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.pose",   self.action_avatar_pose,  description="[兼容] 设置表情",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.say",    self.action_avatar_say,   description="[兼容] 说一句并联动", permission="user", module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.health", self.action_avatar_health, description="[兼容] 健康状态",  permission="user",  module="virtual_avatar")
        ACTION_DISPATCHER.register_action("avatar.switch", self.action_avatar_switch, description="[兼容] 切换形象",  permission="admin", module="virtual_avatar")

        log.info("[avatar] 动作注册完成：virtual_avatar.*（含 avatar.* 兼容别名）")


# 供模块加载器反射的导出
MODULE_CLASS = VirtualAvatarModule
