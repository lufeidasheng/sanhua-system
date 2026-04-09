# -*- coding: utf-8 -*-
"""
LlamaCppServerBackend
- 作为 ModelEngine 的后端：连接本地 llama.cpp server（OpenAI 兼容 API）
- 目标：让 AICore 只做 client，不再自己控制本地模型，从而完全遵循 run_gui.sh 的选模逻辑（llama-server -m xxx.gguf）
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class LlamaCppServerBackend:
    """
    连接本地 llama.cpp server（OpenAI 兼容 API）:
    - GET  /v1/models
    - POST /v1/chat/completions

    说明：
    - 模型由 llama-server 启动参数 -m 决定，这里不负责切换权重文件。
    - select_model 在该后端里会被当成“软选择/记录”，不影响 server 实际加载的 gguf。
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 120.0):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = float(timeout)
        self._selected_model: Optional[str] = None

    # ------------------------- utils -------------------------

    def _get(self, path: str, timeout: float = 8.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw) if raw else {}

    def _post_json(self, path: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=(timeout or self.timeout)) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise RuntimeError(f"llama-server HTTP {e.code}: {body[:500]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"llama-server 连接失败: {e}")

    # ------------------------- engine hooks -------------------------

    def health_check(self) -> Dict[str, Any]:
        try:
            _ = self._get("/v1/models", timeout=5.0)
            return {"ok": True, "backend": "llamacpp_server", "base_url": self.base_url}
        except Exception as e:
            return {"ok": False, "backend": "llamacpp_server", "base_url": self.base_url, "error": str(e)}

    def list_models(self) -> List[Dict[str, Any]]:
        obj = self._get("/v1/models", timeout=6.0)
        data = obj.get("data")
        if isinstance(data, list):
            out: List[Dict[str, Any]] = []
            for it in data:
                if isinstance(it, dict):
                    out.append(it)
                else:
                    out.append({"id": str(it)})
            return out
        return []

    def select_model(self, name: str) -> Dict[str, Any]:
        self._selected_model = (name or "").strip() or None
        return {"ok": True, "selected": self._selected_model or "server-loaded"}

    def chat(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        top_p: float = 0.95,
        **kwargs,
    ) -> str:
        use_model = (model or self._selected_model or "loaded").strip()

        payload: Dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "stream": False,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "top_p": float(top_p),
        }

        for k in ("stop", "presence_penalty", "frequency_penalty", "seed"):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]

        obj = self._post_json("/v1/chat/completions", payload, timeout=self.timeout)

        choices = obj.get("choices") or []
        if isinstance(choices, list) and choices:
            msg = (choices[0] or {}).get("message") or {}
            if isinstance(msg, dict):
                return (msg.get("content") or "") if msg.get("content") is not None else ""

        if "text" in obj:
            return str(obj.get("text") or "")

        return ""
