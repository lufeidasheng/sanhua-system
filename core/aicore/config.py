#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.aicore.backend_config import BackendConfig

log = logging.getLogger("AICoreConfig")


@dataclass
class AICoreConfig:
    """AICore 企业级配置（统一契约版）"""

    identity: Dict[str, str] = field(default_factory=lambda: {
        "user": "用户",
        "assistant": "AI助手",
        "system": "三花聚顶系统",
    })

    # ✅ 关键：这里必须是 BackendConfig 列表（否则 aicore_check 会报 dict 没 enabled）
    backends: List[BackendConfig] = field(default_factory=lambda: [
        BackendConfig(
            name="default_llama_server",
            type="llamacpp_server",
            base_url="http://127.0.0.1:8080",
            model_name="",
            enabled=True,
            priority=1,
            timeout=60,
            retry_times=1,
        )
    ])

    context: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "max_tokens": 4096,
        "max_history": 20,
        "system_prompt": "你是一个有帮助的AI助手。",
    })

    monitoring: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "log_level": "INFO",
    })

    circuit_breaker: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "failure_threshold": 5,
        "reset_timeout": 60,
        "half_open_max_requests": 3,
    })

    protocol: Dict[str, Any] = field(default_factory=lambda: {"enabled": True})

    system: Dict[str, Any] = field(default_factory=lambda: {
        "max_worker_threads": 8,
        "task_timeout": 30,
        "enable_graceful_shutdown": True,
    })

    @classmethod
    def from_env(cls) -> "AICoreConfig":
        cfg = cls()

        cfg.identity["user"] = os.getenv("SANHUA_USER", cfg.identity["user"])
        cfg.identity["assistant"] = os.getenv("SANHUA_ASSISTANT", cfg.identity["assistant"])
        cfg.identity["system"] = os.getenv("SANHUA_SYSTEM", cfg.identity["system"])

        backend_type = os.getenv("SANHUA_BACKEND_TYPE", "llamacpp_server").strip()
        llama_url = os.getenv("SANHUA_LLAMA_URL", os.getenv("SANHUA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080")).strip()
        model_name = os.getenv("SANHUA_ACTIVE_MODEL", os.getenv("SANHUA_MODEL", "")).strip()
        timeout = int(os.getenv("SANHUA_TIMEOUT", os.getenv("SANHUA_LLAMACPP_TIMEOUT", "60")))

        cfg.backends = [
            BackendConfig(
                name="env_backend",
                type=backend_type,
                base_url=llama_url,
                model_name=model_name,
                enabled=True,
                priority=1,
                timeout=timeout,
                retry_times=1,
            )
        ]

        if (t := os.getenv("SANHUA_CONTEXT_TOKENS")):
            try:
                cfg.context["max_tokens"] = int(t)
            except ValueError:
                log.warning(f"无效 SANHUA_CONTEXT_TOKENS={t}，使用默认值 {cfg.context.get('max_tokens')}")

        if (w := os.getenv("SANHUA_WORKER_THREADS")):
            try:
                cfg.system["max_worker_threads"] = int(w)
            except ValueError:
                log.warning(f"无效 SANHUA_WORKER_THREADS={w}，使用默认值 {cfg.system.get('max_worker_threads')}")

        return cfg

    # ✅ BackendManager 会用这个
    def get_active_backends(self) -> List[BackendConfig]:
        items = [b for b in (self.backends or []) if getattr(b, "enabled", False)]
        items.sort(key=lambda x: x.priority)
        return items
