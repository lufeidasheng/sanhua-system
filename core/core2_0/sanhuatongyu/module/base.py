import time
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod
from .meta import ModuleMeta

# 推荐全局日志系统导入
from core.core2_0.sanhuatongyu.logger import get_logger

class BaseModule(ABC):
    """三花聚顶 · 模块基类"""

    def __init__(self, meta: ModuleMeta, context: 'SystemContext'):
        self.meta = meta
        self.context = context
        self.logger = get_logger(f'module.{meta.name}')  # ⭐️ 统一日志实例
        self.config = {}
        self.health_status = 'UNKNOWN'
        self.failure_count = 0
        self.last_restart = 0

        if getattr(self.context, "config_manager", None):
            self.context.config_manager.register_callback('*', self._on_config_update, self.meta.name)

    def _on_config_update(self, key: str, value: Any):
        self.logger.info('config_updated', key=key, value=value)
        if hasattr(self, 'update_config'):
            self.update_config(key, value)

    @abstractmethod
    def preload(self):
        ...

    @abstractmethod
    def setup(self):
        ...

    @abstractmethod
    def start(self):
        ...

    def post_start(self):
        ...

    @abstractmethod
    def stop(self):
        ...

    def on_shutdown(self):
        ...

    @abstractmethod
    def handle_event(self, event_type: str, event_data: dict) -> Optional[dict]:
        ...

    def health_check(self) -> dict:
        return {
            'status': self.health_status,
            'module': self.meta.name,
            'timestamp': time.time(),
            'failure_count': self.failure_count
        }

    def record_failure(self):
        self.failure_count += 1
        self.health_status = 'DEGRADED'
        if self.failure_count >= 3 and time.time() - self.last_restart > 60:
            self.logger.warning('module_restart_triggered', count=self.failure_count)
            if hasattr(self.context, "module_manager"):
                self.context.module_manager.restart_module(self.meta.name)
            self.last_restart = time.time()
            self.failure_count = 0
