#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
from typing import List, Dict, Any, Optional

# ✅ 关键：解决 SystemState 未定义
from core.aicore.system_state import SystemState


class LlamaContext:
    """
    三花聚顶 · LlamaContext（企业增强版）
    - 维护对话历史（user/model）
    - 自动注入 SystemState（让模型“感知系统运行环境”）
    - token 粗估 + 自动裁剪（避免上下文爆炸）
    - 线程安全
    """

    def __init__(self, max_tokens: int = 2048, max_turns: int = 20):
        """
        :param max_tokens: 粗估 token 上限（用于裁剪）
        :param max_turns: 最大对话轮数（硬限制），一轮=用户+助手
        """
        self.max_tokens = int(max_tokens)
        self.max_turns = int(max_turns)

        self.history: List[Dict[str, str]] = []  # [{"user": "...", "model": "..."}]
        self.system_state = SystemState()

        self._lock = threading.RLock()

    # -------------------------
    # System State
    # -------------------------
    def update_system_state(self) -> None:
        """更新系统状态（失败不抛异常，避免影响主流程）"""
        try:
            self.system_state.update()
        except Exception:
            pass

    def get_system_state(self) -> Dict[str, Any]:
        """返回系统状态 dict（失败返回空 dict）"""
        try:
            return self.system_state.get_state()
        except Exception:
            return {}

    # -------------------------
    # History
    # -------------------------
    def add_to_context(self, user_input: str, model_response: str) -> None:
        """追加一轮对话，并触发裁剪"""
        u = (user_input or "").strip()
        m = (model_response or "").strip()

        with self._lock:
            self.history.append({"user": u, "model": m})

            # 1) 轮数硬限制（企业常用：先控“轮数”）
            if self.max_turns > 0 and len(self.history) > self.max_turns:
                self.history = self.history[-self.max_turns :]

            # 2) token 软限制（再控“体积”）
            self._trim_context_locked()

    def reset_context(self) -> None:
        """重置上下文"""
        with self._lock:
            self.history.clear()
            self.system_state = SystemState()

    def get_last(self, n: int) -> List[Dict[str, str]]:
        """获取最近 n 条对话轮（不是消息条数）"""
        n = max(0, int(n))
        with self._lock:
            return list(self.history[-n:])

    # -------------------------
    # Token control (approx)
    # -------------------------
    def _estimate_tokens(self, text: str) -> int:
        """
        粗略 token 估算：
        - 英文：按词数
        - 中文：按字符数/2（保守）
        目标：可控、稳定，不追求绝对精确
        """
        if not text:
            return 0

        # 有空格时按词数估算（偏英文）
        if " " in text:
            return max(1, len(text.split()))

        # 纯中文/无空格：按字符粗估（2字≈1token）
        return max(1, len(text) // 2)

    def _total_tokens_locked(self) -> int:
        total = 0
        for e in self.history:
            total += self._estimate_tokens(e.get("user", ""))
            total += self._estimate_tokens(e.get("model", ""))
        # 把系统状态也算进来
        total += self._estimate_tokens(str(self.get_system_state()))
        return total

    def _trim_context_locked(self) -> None:
        """裁剪直到 token 不超过 max_tokens"""
        if self.max_tokens <= 0:
            return

        total = self._total_tokens_locked()
        while total > self.max_tokens and self.history:
            self.history.pop(0)
            total = self._total_tokens_locked()

    # -------------------------
    # Render
    # -------------------------
    def get_context(self) -> str:
        """
        输出用于 prompt 注入的上下文文本：
        - 历史对话 + SystemState
        """
        with self._lock:
            parts: List[str] = []

            for e in self.history:
                u = e.get("user", "")
                m = e.get("model", "")
                if u:
                    parts.append(f"用户: {u}")
                if m:
                    parts.append(f"助手: {m}")

            st = self.get_system_state()
            if st:
                parts.append(f"System State: {st}")

            return "\n".join(parts).strip()