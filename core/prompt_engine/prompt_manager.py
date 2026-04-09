# -*- coding: utf-8 -*-
from __future__ import annotations

try:
    from core.aicore.prompts.prompt_manager import PromptManager  # type: ignore
except Exception:
    class PromptManager:
        def __init__(self):
            self._persona = "default"
            self._prompts = {"default": {"system": "你是聚核助手，请自然对话。"}}

        def select_persona(self, query: str) -> str:
            return self._persona

        def switch_prompt(self, persona: str):
            self._persona = persona

        def get_system_prompt(self) -> str:
            return self._prompts.get(self._persona, {}).get(
                "system", "你是聚核助手，请自然对话。"
            )

        def export_persona(self) -> dict:
            return {"system": self.get_system_prompt()}
