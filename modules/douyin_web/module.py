"""
三花聚顶 · douyin_web 抖音模块（旗舰/热插拔/系统浏览器/AI副驾占位）🎬
版本：1.2.0
作者：三花聚顶开发团队
"""

import os
import time
import threading
import webbrowser
from typing import Optional, Dict, Any

from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTION_DISPATCHER

logger = get_logger("douyin_web")

class DouyinWebModule(BaseModule):
    """
    三花聚顶 · 抖音网页版（系统浏览器模式/动作注册/健康/热插拔单例）
    """
    VERSION = "1.2.0"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self.config = getattr(meta, "config", {}) if meta else {}
        self._last_open = 0
        self._registered = False
        logger.info(f"{getattr(self.meta, 'name', 'douyin_web')} v{self.VERSION} 初始化完成")

    # --- 抽象方法实现 ---
    def preload(self):
        logger.info(f"{getattr(self.meta, 'name', 'douyin_web')} preload 开始")
        self._register_actions()
        logger.info(f"{getattr(self.meta, 'name', 'douyin_web')} preload 结束")

    def setup(self):
        logger.info(f"{getattr(self.meta, 'name', 'douyin_web')} setup 开始")
        self._register_actions()
        if hasattr(self.context, "event_bus") and self.context.event_bus:
            self.context.event_bus.subscribe("douyin.open", self.handle_event)
        logger.info(f"{getattr(self.meta, 'name', 'douyin_web')} setup 结束")

    def start(self):
        logger.info("抖音模块启动完成")

    def stop(self):
        logger.info("抖音模块停止/已卸载")

    def handle_event(self, event_name, data=None):
        if event_name == "douyin.open":
            logger.info("收到 douyin.open 事件，准备打开抖音网页版")
            return self.open_douyin_action()
        logger.info(f"未知事件: {event_name}")
        return None

    def health_check(self):
        status = {
            "status": "OK",
            "module": getattr(self.meta, 'name', 'douyin_web'),
            "version": self.VERSION,
            "last_open": self._last_open
        }
        logger.debug("健康检查", extra=status)
        return status

    def cleanup(self):
        if hasattr(ACTION_DISPATCHER, "unregister_action"):
            ACTION_DISPATCHER.unregister_action("open_douyin")
        logger.info("open_douyin 动作反注册完成")

    # --- 动作注册 ---
    def _register_actions(self):
        if hasattr(self.context, "register_action"):
            if not self._registered:
                self.context.register_action("open_douyin", func=self.open_douyin_action)
                self._registered = True
                logger.info("通过 context.register_action 注册 open_douyin")
        else:
            if "open_douyin" not in [a["name"] for a in ACTION_DISPATCHER.list_actions(detailed=True)]:
                ACTION_DISPATCHER.register_action(
                    name="open_douyin",
                    func=self.open_douyin_action,
                    aliases=["打开抖音", "刷抖音", "看抖音", "启动抖音", "抖音"],
                    description="打开抖音网页版（系统浏览器模式）",
                    permission="user",
                    module="douyin_web"
                )
                logger.info("注册标准动作: open_douyin")

    # --- 核心动作：系统浏览器打开 ---
    def open_douyin_action(self, context=None, params=None, **kwargs) -> str:
        self._last_open = time.time()
        homepage = self.config.get("homepage_url", "https://www.douyin.com")
        try:
            logger.info(f"正在通过系统浏览器打开: {homepage}")
            webbrowser.open(homepage)
            return f"🎬 已通过系统浏览器唤起抖音网页版: {homepage}"
        except Exception as e:
            logger.error(f"❌ 打开抖音网页版失败: {str(e)}")
            return f"❌ 打开抖音网页版失败: {str(e)}"

# ==== 模块元数据 ====
MODULE_METADATA = {
    "name": "douyin_web",
    "version": "1.2.0",
    "description": "抖音网页版集成模块（系统浏览器版），支持AI副驾扩展与热插拔",
    "author": "三花聚顶开发团队",
    "entry": "modules.douyin_web",
    "actions": [
        {
            "name": "open_douyin",
            "description": "通过系统默认浏览器打开抖音网页版",
            "permission": "user",
            "aliases": ["打开抖音", "刷抖音", "看抖音", "启动抖音", "抖音"]
        }
    ],
    "dependencies": [],
    "config_schema": {
        "homepage_url": {
            "type": "string",
            "default": "https://www.douyin.com",
            "description": "抖音主页URL"
        }
    }
}

MODULE_CLASS = DouyinWebModule

# ==== 注册辅助 ====
def register_actions(dispatcher, context=None):
    mod = DouyinWebModule(meta=dispatcher.get_module_meta("douyin_web"), context=context)
    dispatcher.register_action(
        name="open_douyin",
        func=mod.open_douyin_action,
        aliases=MODULE_METADATA["actions"][0]["aliases"],
        description=MODULE_METADATA["actions"][0]["description"],
        permission="user"
    )
    logger.info("抖音模块动作注册完成")
