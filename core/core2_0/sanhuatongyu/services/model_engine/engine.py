# -*- coding: utf-8 -*-
from typing import Dict, Optional, List, Any
from .router import Router


class ModelEngine:
    """
    🌸 三花聚顶 · 模型中控引擎（企业增强版）
    - 统一管理模型后端（本地 / 云 / 混合）
    - 自动模型选择：根据任务类型选择最优模型
    - 支持强制路由（debug / 开发用）
    """

    def __init__(self, meta=None, context=None):
        self.meta = meta
        self.context = context
        self.backends: Dict[str, Any] = {}         # 后端池
        self.active_backend: Optional[str] = None   # 默认使用的后端
        self.forced_backend: Optional[str] = None   # 强制路由
        self.router = Router()                      # 智能模型选择器

    # ---------------- 注册模型后端 ----------------
    def register_backend(self, name: str, backend):
        """
        name: 后端名称，如 "local_llama" / "cloud_openai"
        backend: 具有 chat(messages, model, stream=False) 方法的对象
        """
        self.backends[name] = backend

    # ---------------- 默认后端选择 ----------------
    def use(self, name: str) -> bool:
        if name in self.backends:
            self.active_backend = name
            return True
        return False

    # ---------------- 强制制定后端（调试模式） ----------------
    def set_forced_backend(self, name: Optional[str]):
        self.forced_backend = name

    # ---------------- 获取实际应使用的后端 ----------------
    def _select_backend(self):
        # 优先强制后端
        if self.forced_backend and self.forced_backend in self.backends:
            return self.backends[self.forced_backend]

        # 否则默认后端
        if self.active_backend and self.active_backend in self.backends:
            return self.backends[self.active_backend]

        raise RuntimeError("❌ 没有可用后端，请先调用 model_engine.use('local_llama')")

    # ---------------- 核心：统一模型调用接口 ----------------
    def chat(self, messages: List[Dict[str, str]], stream: bool = False):
        """
        messages: OpenAI 风格的 ChatCompletion 消息列表
        stream: 是否流式输出

        🚀 关键变化：在这里做模型智能选择
        """
        backend = self._select_backend()

        # 让 Router 决定使用哪个模型
        model_choice = self.router.choose(messages)

        # 根据模型名 → 选择对应 GGUF 文件名（本地运行）
        if model_choice == "qwen":
            model_name = "qwen3-latest.gguf"
        else:
            model_name = "llama3-8b.gguf"

        # 调用后端
        return backend.chat(messages, model=model_name, stream=stream)