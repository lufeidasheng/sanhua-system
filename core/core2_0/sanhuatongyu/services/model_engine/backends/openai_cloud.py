# core/core2_0/sanhuatongyu/services/model_engine/backends/openai_cloud.py
# -*- coding: utf-8 -*-
from typing import Dict, Any, Iterable, List
import json, requests
try:
    from sseclient import SSEClient
except Exception:
    SSEClient = None

class OpenAICloudBackend:
    def __init__(self, cfg: Dict[str, Any], logger):
        self.log = logger
        self.base = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.api_key = cfg.get("api_key", "")
        self.default_model = cfg.get("model", "gpt-4o-mini")
        self.timeout = int(cfg.get("timeout_s", 120))

    def health(self) -> bool:
        try:
            r = requests.get(self.base + "/models",
                             headers={"Authorization": f"Bearer {self.api_key}"}, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, messages: List[Dict[str,str]], model: str=None,
             temperature: float=0.7, max_tokens: int=2048, stream: bool=True) -> Iterable[str]:
        url = self.base + "/chat/completions"
        payload = {
            "model": model or self.default_model,
            "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": stream
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=self.timeout, stream=stream)
        r.raise_for_status()
        if stream:
            if SSEClient is None:
                raise RuntimeError("sseclient not installed for streaming")
            client = SSEClient(r)
            for ev in client.events():
                if ev.data == "[DONE]": break
                data = json.loads(ev.data)
                delta = data["choices"][0]["delta"].get("content", "")
                if delta: yield delta
        else:
            data = r.json()
            yield data["choices"][0]["message"]["content"]
