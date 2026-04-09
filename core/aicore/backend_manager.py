#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
import logging
from typing import Dict, Optional, Any, List, Tuple

from core.aicore.model_backend import ModelBackend
from core.aicore.backend_config import BackendConfig
from core.aicore.circuit_breaker import CircuitBreaker

log = logging.getLogger("BackendManager")


class BackendManager:
    """
    后端管理器：负责管理和切换后端模型

    企业级标准点：
    - 统一消费 AICoreConfig.get_active_backends() -> List[BackendConfig]
    - 支持 switch_backend(name) / switch_backend(obj) 两种调用（兼容检查脚本）
    - 后端初始化失败不影响系统启动（可降级）
    - 状态可观测：get_backend_status() 返回配置/熔断/后端信息
    - 线程安全：RLock
    """

    def __init__(self, config):
        self.config = config

        # name -> backend instance
        self.backends: Dict[str, ModelBackend] = {}

        # 当前活跃 backend instance
        self.active_backend: Optional[ModelBackend] = None

        # name -> BackendConfig
        self.backend_configs: Dict[str, BackendConfig] = {}

        # name -> CircuitBreaker
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

        self._lock = threading.RLock()

        self._initialize_backends()

    # ------------------------------------------------------------
    # init
    # ------------------------------------------------------------
    def _initialize_backends(self) -> None:
        backends = []
        try:
            backends = list(self.config.get_active_backends())
        except Exception as e:
            log.error(f"❌ get_active_backends() 失败: {e}", exc_info=True)

        if not backends:
            log.warning("⚠️ 未发现任何启用的后端配置（backends 为空）")
            return

        for backend_cfg in backends:
            name = getattr(backend_cfg, "name", "") or "unnamed_backend"
            try:
                backend = self._create_backend(backend_cfg)
                if not backend:
                    log.warning(f"⚠️ 后端创建返回 None: {name}")
                    continue

                self.backends[name] = backend
                self.backend_configs[name] = backend_cfg

                # 熔断器：当前用简洁型 CircuitBreaker（你也可以后续换成增强版）
                self.circuit_breakers[name] = CircuitBreaker()

                if self.active_backend is None:
                    self.active_backend = backend
                    log.info(f"✅ Active backend = {name}")

            except Exception as e:
                log.error(f"❌ 后端初始化失败: {name} - {e}", exc_info=True)

    def _create_backend(self, cfg: BackendConfig) -> Optional[ModelBackend]:
        t = (getattr(cfg, "type", "") or "").strip().lower()

        if t in ("llamacpp_server", "server", "llama_server", "llamacpp_http"):
            from core.aicore.backends.llamacpp_server import LlamaCppServerBackend
            return LlamaCppServerBackend(cfg)

        # 你后续要 openai 再补：
        # if t in ("openai",):
        #     from core.aicore.backends.openai import OpenAIBackend
        #     return OpenAIBackend(cfg)

        log.warning(f"⚠️ 未支持的后端类型: {t} (name={getattr(cfg, 'name', '')})")
        return None

    # ------------------------------------------------------------
    # switching
    # ------------------------------------------------------------
    def switch_backend(self, backend_ref) -> bool:
        """
        兼容两种调用方式（企业级鲁棒性）：
        1) switch_backend("env_backend")  # 传后端名（推荐）
        2) switch_backend(backend_obj)    # 传后端对象（兼容 aicore_check.py）
        """
        with self._lock:
            # Case A: 传入的是后端对象（按对象反查 name）
            for name, obj in self.backends.items():
                if obj is backend_ref:
                    self.active_backend = obj
                    log.info(f"✅ switch_backend(obj) -> {name}")
                    return True

            # Case B: 传入的是后端名（或可转字符串）
            name = str(backend_ref)
            if name in self.backends:
                self.active_backend = self.backends[name]
                log.info(f"✅ switch_backend(name) -> {name}")
                return True

            log.error(f"❌ switch_backend 失败，未找到: {backend_ref}")
            return False

    def get_next_available_backend(self) -> Optional[ModelBackend]:
        """
        获取下一个可用后端：
        - 按 config.get_active_backends() 的 priority 顺序（由 config 控制）
        - 熔断 open 状态则跳过
        """
        with self._lock:
            try:
                ordered = list(self.config.get_active_backends())
            except Exception:
                ordered = list(self.backend_configs.values())

            for cfg in ordered:
                name = getattr(cfg, "name", None)
                if not name or name not in self.backends:
                    continue

                cb = self.circuit_breakers.get(name)
                if cb and getattr(cb, "is_open", False):
                    continue

                return self.backends[name]
        return None

    # ------------------------------------------------------------
    # observability
    # ------------------------------------------------------------
    def get_backend_status(self) -> Dict[str, Any]:
        """
        返回所有后端状态（给 GUI/CLI/检查脚本用）
        """
        with self._lock:
            out: Dict[str, Any] = {}
            for name, backend in self.backends.items():
                cfg = self.backend_configs.get(name)
                cb = self.circuit_breakers.get(name)

                # 尝试健康检查（不阻塞、不抛出）
                healthy = None
                try:
                    if hasattr(backend, "health_check"):
                        healthy = bool(backend.health_check())
                except Exception:
                    healthy = None

                info: Dict[str, Any] = {}
                try:
                    if hasattr(backend, "get_backend_info"):
                        info = backend.get_backend_info() or {}
                except Exception:
                    info = {}

                out[name] = {
                    "is_active": backend == self.active_backend,
                    "healthy": healthy,
                    "config": cfg.to_dict() if cfg else {},
                    "circuit_breaker": cb.metrics() if cb else None,
                    "backend_info": info,
                }
            return out

    def list_backend_names(self) -> List[str]:
        with self._lock:
            return list(self.backends.keys())

    def get_active_backend_name(self) -> Optional[str]:
        with self._lock:
            for name, obj in self.backends.items():
                if obj is self.active_backend:
                    return name
        return None

    # ------------------------------------------------------------
    # failure / success hooks (optional)
    # ------------------------------------------------------------
    def record_backend_success(self, backend_name: Optional[str] = None) -> None:
        """
        可选：当后端调用成功时，更新熔断器
        """
        name = backend_name or self.get_active_backend_name()
        if not name:
            return
        cb = self.circuit_breakers.get(name)
        if cb:
            try:
                cb.record_success()
            except Exception:
                pass

    def record_backend_failure(self, backend_name: Optional[str] = None) -> None:
        """
        可选：当后端调用失败时，更新熔断器
        """
        name = backend_name or self.get_active_backend_name()
        if not name:
            return
        cb = self.circuit_breakers.get(name)
        if cb:
            try:
                cb.record_failure()
            except Exception:
                pass