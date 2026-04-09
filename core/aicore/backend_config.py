#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class BackendConfig:
    """
    后端配置契约（企业版）
    - BackendManager 统一消费这个结构
    - AICoreConfig 可以从 env / dict 生成它
    """
    name: str
    type: str                      # llamacpp_server | openai | ...
    base_url: str = "http://127.0.0.1:8080"
    model_name: str = ""
    enabled: bool = True
    priority: int = 1              # 数字越小优先级越高
    timeout: int = 60              # seconds
    retry_times: int = 1

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BackendConfig":
        return cls(
            name=str(d.get("name", "unnamed_backend")),
            type=str(d.get("type", "llamacpp_server")),
            base_url=str(d.get("base_url", d.get("url", "http://127.0.0.1:8080"))),
            model_name=str(d.get("model_name", d.get("model", ""))),
            enabled=bool(d.get("enabled", True)),
            priority=int(d.get("priority", 1)),
            timeout=int(d.get("timeout", 60)),
            retry_times=int(d.get("retry_times", 1)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "enabled": self.enabled,
            "priority": self.priority,
            "timeout": self.timeout,
            "retry_times": self.retry_times,
        }
