# -*- coding: utf-8 -*-
from typing import List, Dict


class Router:
    """
    三花聚顶 · 模型智能路由器
    根据用户输入的任务特征 → 自动选择最优模型
    """

    def __init__(self):
        # 可扩展模型池
        self.backends = {
            "qwen": "local_llama",     # 对话 / 表达 / 日常
            "llama": "local_llama"     # 推理 / 架构 / 深度分析
        }

    def choose(self, messages: List[Dict[str, str]]) -> str:
        """
        输入为 ChatCompletion 标准格式
        根据用户 query 自动判断模型类型
        """
        user_text = messages[-1]["content"].strip()

        # ====== 规则层（可学习） ======
        # 情感表达相关 → qwen
        if any(k in user_text for k in ["难受", "怎么办", "感觉", "我想", "喜欢", "关系"]):
            return "qwen"

        # 架构 / 推理 / 技术分析 → llama
        if any(k in user_text for k in ["架构", "原理", "推理", "本质", "模型设计", "系统设计"]):
            return "llama"

        # 翻译 / 模仿语气 → qwen
        if any(k in user_text for k in ["翻译", "改写", "口语化"]):
            return "qwen"

        # 长文本总结 → llama
        if len(user_text) > 120:
            return "llama"

        # 默认日常对话 → qwen
        return "qwen"