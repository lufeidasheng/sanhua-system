import os
import time
import requests
from typing import Dict, Any


class LlamaCppModelAdapter:
    """
    🌸 三花聚顶 · llama.cpp 模型服务适配器（支持健康检查 + 自动启动 + 推理调用）
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 8080)
        self.api_endpoint = config.get("api_endpoint", "/completion")
        self.start_command = config.get("start_command")
        self.name = config.get("name", "llama.cpp")

    def is_healthy(self) -> bool:
        try:
            resp = requests.get(f"http://{self.host}:{self.port}/health", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def start(self):
        if self.start_command:
            print(f"🟡 正在尝试启动模型服务：{self.name}")
            os.system(self.start_command)
            time.sleep(2)
        else:
            print("⚠️ 未设置启动命令，无法启动模型服务")

    def generate(self, prompt: str, n_predict: int = 100) -> str:
        payload = {
            "prompt": prompt,
            "n_predict": n_predict,
            "stream": False
        }
        try:
            url = f"http://{self.host}:{self.port}{self.api_endpoint}"
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json().get("content", "").strip()
        except Exception as e:
            return f"[模型调用失败] {str(e)}"
