import os
import yaml
from typing import Dict, Any, Optional

class PromptManager:
    """
    AI Prompt 管理器，支持多场景 / 多角色 / 热切换
    """
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.join(os.path.dirname(__file__), "builtin")
        self.prompts: Dict[str, Dict[str, Any]] = {}
        self.active_prompt: Optional[str] = None
        self._load_all_prompts()

        # ✅ 强制挂载三花聚顶核心人格
        if "assistant_zh" in self.prompts:
            self.active_prompt = "assistant_zh"

    def _load_all_prompts(self):
        """自动加载所有yaml格式prompt"""
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

        for file in os.listdir(self.base_dir):
            if file.endswith(".yaml"):
                name = os.path.splitext(file)[0]
                with open(os.path.join(self.base_dir, file), "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    self.prompts[name] = data

        # 如果首次加载且未激活，则默认第一个
        if self.prompts and not self.active_prompt:
            self.active_prompt = next(iter(self.prompts))

    def list_prompts(self) -> Dict[str, Dict[str, Any]]:
        """列出所有可用prompt"""
        return self.prompts

    def get_prompt(self, name: Optional[str] = None) -> Dict[str, Any]:
        """获取指定prompt内容，未指定返回当前激活"""
        key = name or self.active_prompt
        return self.prompts.get(key, {})

    def switch_prompt(self, name: str) -> bool:
        """切换活跃prompt"""
        if name in self.prompts:
            self.active_prompt = name
            return True
        return False

    def reload(self):
        """热加载全部Prompt（支持文件热更/市场更新）"""
        self.prompts.clear()
        self._load_all_prompts()

    def select_persona(self, query: str) -> Optional[str]:
        """
        简单关键词行为人格切换（可替换为 AI + 状态机）
        """
        q = query.lower()

        # 根据问话内容判断
        if any(k in q for k in ["代码", "编程", "开发"]):
            return "dev_coder" if "dev_coder" in self.prompts else self.active_prompt

        if any(k in q for k in ["聊天", "轻松", "放松"]):
            return "assistant_zh"

        return self.active_prompt


def get_prompt_manager():
    return PromptManager()