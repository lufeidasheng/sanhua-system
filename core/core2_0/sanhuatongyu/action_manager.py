#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶 · ActionManager
支持：全局动作注册/分发/动态发现/注入context/线程安全
"""

import threading
from typing import Callable, Dict, List, Optional, Any
import inspect

from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger("ActionManager")

class ActionMeta:
    """
    动作元信息（每个动作一个唯一名称）
    """
    def __init__(
        self,
        name: str,
        func: Callable,
        description: str = "",
        permission: str = "user",
        module: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.func = func
        self.description = description
        self.permission = permission
        self.module = module or "core"
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission,
            "module": self.module,
            "extra": self.extra
        }

class ActionManager:
    """
    企业级全局动作管理器
    - 支持注册/查找/列出/调用/反注册/线程安全
    - 支持 context 注入 (主控赋值/CLI全局分发)
    """
    def __init__(self, context: Optional[Any] = None):
        self._actions: Dict[str, ActionMeta] = {}
        self._lock = threading.RLock()
        self.context = context

    def register_action(
        self,
        name: str,
        func: Callable,
        description: str = "",
        permission: str = "user",
        module: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """注册动作，name需唯一"""
        with self._lock:
            if name in self._actions:
                log.warning(f"动作已存在，自动覆盖: {name}")
            self._actions[name] = ActionMeta(
                name=name,
                func=func,
                description=description,
                permission=permission,
                module=module,
                extra=extra
            )
            log.info(f"注册动作: {name} (模块: {module or 'core'})")

    def unregister_action(self, name: str):
        with self._lock:
            if name in self._actions:
                del self._actions[name]
                log.info(f"移除动作: {name}")
            else:
                log.warning(f"移除失败，未找到动作: {name}")

    def get_action(self, name: str) -> Optional[ActionMeta]:
        with self._lock:
            return self._actions.get(name)

    def list_actions(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                action.to_dict()
                for action in self._actions.values()
                if (module is None or action.module == module)
            ]

    def call_action(self, name: str, *args, **kwargs) -> Any:
        """
        调用动作（自动补充context作为第一个参数，如果目标函数需要）
        """
        with self._lock:
            action = self._actions.get(name)
            if not action:
                raise ValueError(f"未找到动作: {name}")
            log.info(f"执行动作: {name}")
            # 支持自动注入context
            try:
                params = list(inspect.signature(action.func).parameters)
                # 判断是否需要context作为第一个参数（如 context/self/master/ctx）
                if self.context and params and params[0] in ("context", "self", "ctx", "master"):
                    return action.func(self.context, *args, **kwargs)
                else:
                    return action.func(*args, **kwargs)
            except Exception as e:
                log.error(f"执行动作失败: {e}")
                raise

    def clear(self):
        with self._lock:
            self._actions.clear()
            log.info("所有动作已清空")

# === 推荐全局单例 ===
ACTION_MANAGER = ActionManager()

# ======= 用法/测试示例 =======
if __name__ == "__main__":
    # Demo
    def hello(ctx, name):
        return f"Hello, {name}! (context:{ctx})"

    # 设置全局 context，主控里可以是 SanHuaTongYu/context
    ACTION_MANAGER.context = "DEMO_CONTEXT"
    ACTION_MANAGER.register_action(
        name="demo.hello",
        func=hello,
        description="打招呼",
        module="demo"
    )
    print("所有动作：", ACTION_MANAGER.list_actions())
    print("调用demo.hello:", ACTION_MANAGER.call_action("demo.hello", "鹏鹏"))
