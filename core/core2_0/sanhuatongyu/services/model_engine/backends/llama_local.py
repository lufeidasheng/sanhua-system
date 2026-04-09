# core/core2_0/sanhuatongyu/services/model_engine/backends/llama_local.py
# -*- coding: utf-8 -*-

from typing import Dict, Any, Iterable, List
import json, requests
try:
    from sseclient import SSEClient
except Exception:
    SSEClient = None

from .llamacpp_controller import LlamaCppController


class LlamaLocalBackend:
    """
    🌸 三花聚顶 · 本地 llama.cpp 推理后端（支持热切换模型）
    - 自动确保 llama.cpp server 存活
    - 支持 ChatCompletion（流 / 非流）
    - ✅ 新增：set_model() 用于与 ModelEngine 联动
    """
    def __init__(self, controller: LlamaCppController, logger=None):
        self.ctrl = controller
        self.log = logger or (lambda *a, **k: None)
        self.api_key = "dev-local"

    # ---------------- 新增（供 ModelEngine 调用） ----------------
    def set_model(self, model_path: str):
        """
        切换当前模型（无需重启 GUI）
        """
        self.ctrl.set_model(model_path)
        self.log(f"[LlamaLocalBackend] ✅ 切换模型 → {model_path}")

    # ---------------- 健康检查 ----------------
    def health(self) -> bool:
        if not self.ctrl.ensure_up():
            return False
        try:
            r = requests.get(f"{self.ctrl.endpoint()}/v1/models",
                             headers={"Authorization": f"Bearer {self.api_key}"}, timeout=5)
            return r.status_code == 200
        except:
            return False

    def base_url(self) -> str:
        return f"{self.ctrl.endpoint()}/v1"

    # ---------------- ChatCompletion 核心 ----------------
    def chat(self, messages: List[Dict[str, str]], model: str=None,
             temperature: float=0.2, max_tokens: int=1024, stream: bool=False) -> Iterable[str]:
        """
        model:
            如果是文件路径（*.gguf） → 直接切换模型
            如果是模型名 → 传给 llama.cpp
        """
        # ✅ 自动切换模型（本地）：
        if model:
            # 本地 GGUF 文件路径 → 直接加载
            if model.endswith(".gguf"):
                self.ctrl.set_model(model)
            else:
                # 也支持传模型名字（如 llama3:8b）
                self.log(f"[chat] 使用模型名: {model}")

        if not self.ctrl.ensure_up():
            raise RuntimeError("❌ llama.cpp server 未就绪")

        url = self.base_url() + "/chat/completions"
        payload = {
            "model": model or (self.ctrl.p.model_path),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180, stream=stream)
        r.raise_for_status()

        if stream:
            if SSEClient is None:
                raise RuntimeError("未安装 sseclient，无法流式输出")
            client = SSEClient(r)
            for ev in client.events():
                if ev.data == "[DONE]":
                    break
                data = json.loads(ev.data)
                delta = data["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
        else:
            data = r.json()
            yield data["choices"][0]["message"]["content"]

    # ---------------- 控制接口 ----------------
    def start(self):   return self.ctrl.start()
    def stop(self):    return self.ctrl.stop()
    def restart(self): return self.ctrl.restart()
    def status(self):  return self.ctrl.get_status()