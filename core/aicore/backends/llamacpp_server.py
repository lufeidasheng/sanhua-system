#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import requests
from typing import Any, Dict, List, Union
from concurrent.futures import Future

from core.aicore.model_backend import ModelBackend
from core.aicore.backend_config import BackendConfig


class LlamaCppServerBackend(ModelBackend):
    """
    llama.cpp server 后端（OpenAI 兼容）
    - base_url: http://127.0.0.1:8080
    - /v1/chat/completions
    - /v1/models
    """

    def __init__(self, cfg: BackendConfig):
        self.cfg = cfg
        self.base = (cfg.base_url or "http://127.0.0.1:8080").rstrip("/")
        self.timeout = int(cfg.timeout or 60)

    def chat(self, query: str, **kwargs) -> str:
        # 允许 ExtensibleAICore 传 messages；没有就用最简单的 messages
        messages = kwargs.get("messages")
        if not messages:
            messages = [{"role": "user", "content": query}]

        payload = {
            "model": self.cfg.model_name or "local",
            "messages": messages,
            "stream": False,
        }
        # 透传常用采样参数（可选）
        for k in ("temperature", "top_p", "max_tokens", "stop"):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]

        url = f"{self.base}/v1/chat/completions"
        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        # OpenAI 格式：choices[0].message.content
        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return str(data)

    def list_models(self) -> List[Union[str, Dict]]:
        url = f"{self.base}/v1/models"
        r = requests.get(url, timeout=min(10, self.timeout))
        r.raise_for_status()
        data = r.json()
        # OpenAI list models: {"data":[{"id":...},...]}
        items = data.get("data") or []
        return items

    def health_check(self) -> bool:
        # 优先 /health（如果你有 manager），否则探测 /v1/models
        for path in ("/health", "/v1/models"):
            try:
                r = requests.get(f"{self.base}{path}", timeout=5)
                if 200 <= r.status_code < 300:
                    return True
            except Exception:
                pass
        return False

    def get_backend_info(self) -> Dict[str, Any]:
        return {
            "type": "llamacpp_server",
            "base_url": self.base,
            "model_name": self.cfg.model_name,
            "timeout": self.timeout,
        }
