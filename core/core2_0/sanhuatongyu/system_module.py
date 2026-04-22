from typing import Optional
from .module.base import BaseModule
from .module.meta import ModuleMeta
from .logger import get_logger

class SystemModule(BaseModule):
    """三花聚顶 · 系统管理核心模块"""

    def __init__(self, meta: ModuleMeta, context: 'SystemContext'):
        super().__init__(meta, context)
        # 全模块统一结构化日志
        self.logger = get_logger('system_core')

    def preload(self):
        self.logger.info('system_module_preload')

    def setup(self):
        self.logger.info('system_module_setup')

    def start(self):
        self.logger.info('system_module_start')

    def post_start(self):
        self.logger.info('system_module_post_start')

    def stop(self):
        self.logger.info('system_module_stop')

    def on_shutdown(self):
        self.logger.info('system_module_shutdown')

    def handle_event(self, event_type: str, event_data: dict) -> Optional[dict]:
        if event_type == 'SYSTEM_STATUS_REQUEST':
            return self.get_system_status()
        elif event_type == 'RESTART_MODULE':
            return self.restart_module(event_data.get('module_name'))
        return None

    def get_system_status(self) -> dict:
        reader = getattr(self.context, "get_system_status", None)
        status = reader() if callable(reader) else {
            'status': 'UNKNOWN',
            'system_running': False,
            'uptime': 0.0,
            'modules_loaded': 0,
        }
        self.logger.debug('system_status_report', extra=status)
        return status

    def restart_module(self, module_name: str):
        result = self.context.module_manager.restart_module(module_name)
        log_data = {'module': module_name, 'result': result}
        self.logger.info('restarting_module', extra=log_data)
        return {'status': 'success' if result else 'failed', 'module': module_name}
