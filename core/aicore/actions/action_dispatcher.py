import os
import yaml
from queue import Queue
from typing import List, Dict, Any, Optional, Callable, Union

from ..actions import action_handlers

class ActionDispatcher:
    """
    🌸 三花聚顶 · ActionDispatcher
    动作分发核心，支持多动作源、配置驱动、统一调用链
    """
    def __init__(self, core, config_path: Optional[str] = None):
        self.core = core
        # 动作表结构：[{name, keywords, function}]
        self.actions: List[Dict[str, Any]] = []
        self.action_map: Dict[str, Dict[str, Any]] = {}  # name->动作配置
        self.config_path = config_path
        self._load_actions()

    def _default_action_path(self):
        # 自动寻找actions.yaml
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "..", "..", "actions.yaml"),
            os.path.join(base_dir, "actions.yaml"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return os.path.abspath(p)
        return None

    def _load_actions(self):
        # 优先用传入路径，否则默认路径
        path = self.config_path or self._default_action_path()
        if not path or not os.path.exists(path):
            print(f"⚠️ 动作配置文件未找到: {path}")
            self.actions = []
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not data:
                print("⚠️ 动作配置文件为空或格式错误！")
                self.actions = []
                return
            # 兼容["name", "keywords", "function"/"action"]结构
            self.actions = []
            for action in data:
                if isinstance(action, dict):
                    name = action.get("name") or action.get("action")
                    keywords = action.get("keywords", [])
                    function = action.get("function") or action.get("action")
                    self.actions.append({
                        "name": name,
                        "keywords": keywords,
                        "function": function
                    })
                    self.action_map[name] = self.actions[-1]

    def match_action(self, query: str) -> Optional[Dict[str, Any]]:
        """
        根据自然语言query匹配动作定义
        :return: 动作字典 {name, keywords, function}
        """
        for action in self.actions:
            for keyword in action.get("keywords", []):
                if keyword and keyword in query:
                    return action
        return None

    def execute_action(self, function_name: str, query: str, *args, **kwargs) -> Any:
        """
        执行动作函数
        :return: 动作执行结果，可直接返回给主控/日志
        """
        func = getattr(action_handlers, function_name, None)
        if callable(func):
            try:
                return func(self.core, query, *args, **kwargs)
            except Exception as e:
                print(f"❌ 动作执行失败[{function_name}]：{e}")
                return f"动作[{function_name}]执行失败：{e}"
        else:
            print(f"⚠️ 动作函数未找到: '{function_name}'")
            return f"未找到动作函数：{function_name}"

    def execute_action_and_notify(
        self,
        function_name: str,
        action_name: str,
        query: str,
        result_queue: Queue,
        *args, **kwargs
    ):
        """
        执行动作并通过队列发送执行结果通知
        """
        try:
            result = self.execute_action(function_name, query, *args, **kwargs)
            result_queue.put(f"动作 '{action_name}' 执行完成: {result}")
        except Exception as e:
            result_queue.put(f"动作 '{action_name}' 执行失败：{e}")

    def list_actions(self) -> List[str]:
        """返回所有注册动作名"""
        return [action.get("name") for action in self.actions]

    def get_action_function(self, action_name: str) -> Optional[str]:
        """通过动作名查找function名称"""
        action = self.action_map.get(action_name)
        return action["function"] if action else None

    def reload(self):
        """重新加载动作配置（热加载支持）"""
        self._load_actions()

# 🌟【使用示例】
if __name__ == "__main__":
    from queue import Queue
    class DummyCore:
        pass
    dispatcher = ActionDispatcher(DummyCore())
    print("可用动作：", dispatcher.list_actions())
    test_query = "播放音乐"
    matched = dispatcher.match_action(test_query)
    print("匹配动作:", matched)
    if matched:
        res = dispatcher.execute_action(matched["function"], test_query)
        print("动作执行结果:", res)
