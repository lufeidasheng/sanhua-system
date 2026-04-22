import time
from typing import Dict, Any, Optional, Protocol, runtime_checkable
from .logger import get_logger, I18nManager
from .config import ConfigManager
from .module.manager import ModuleManager
from .security.access_control import AccessControl
from .security.security_manager import SecurityManager
from .action_dispatcher import dispatcher as global_dispatcher
from .events import init_event_bus, get_event_bus

@runtime_checkable
class IEventBus(Protocol):
    def publish(self, event_type: str, payload: Dict[str, Any]) -> None: ...
    def subscribe(self, event_type: str, handler: callable) -> None: ...
    def unsubscribe(self, event_type: str, handler: callable) -> None: ...
    def update_rate_limits(self, *, global_limit: Optional[int] = None, per_event_limit: Optional[int] = None) -> None: ...
    def set_access_control(self, ac: AccessControl) -> None: ...
    def get_metrics(self) -> Dict[str, Any]: ...

class SystemContext:
    """
    三花聚顶 · 全局上下文对象
    核心集成：配置管理、权限风控、安全审计、事件总线、动作调度器、模块管理、国际化日志与服务注册
    """

    def __init__(self, global_config_path: str, user_config_path: str, dev_mode: bool):
        # 1. 日志
        self.logger = get_logger("context")
        self.logger.info('context_init_start', mode='开发' if dev_mode else '生产')

        # 2. 系统基础状态
        self.services: Dict[str, Any] = {}
        self.dev_mode = dev_mode
        self.system_running = False
        self.start_time = time.time()

        # 3. 配置管理
        self.config_manager = ConfigManager(global_config_path, user_config_path)
        # 4. 国际化（可切换，默认zh_CN）
        I18nManager.set_language("zh_CN")

        # 5. 权限体系与安全风控
        self.access_control = self._init_access_control()
        self.security_manager = SecurityManager(
            log_file="logs/security.log",
            policy_file="config/security_policy.json"
        )

        # 6. 事件总线（本地 events.py，自动注入权限与限流）
        event_bus_config = self.config_manager.get('event_bus', {
            'thread_pool_size': 10,
            'global_rate_limit': 1000,
            'per_event_rate_limit': 100,
        })
        self.event_bus: Optional[IEventBus] = None
        try:
            init_event_bus(event_bus_config)
            candidate = get_event_bus()
            if not isinstance(candidate, IEventBus):
                self.logger.error("event_bus_interface_invalid")
            self.event_bus = candidate
            if self.event_bus and hasattr(self.event_bus, 'set_access_control'):
                self.event_bus.set_access_control(self.access_control)
                self.logger.info("event_bus_access_control_success")
            if self.event_bus and hasattr(self.event_bus, 'update_rate_limits'):
                if 'global_rate_limit' in event_bus_config:
                    self.event_bus.update_rate_limits(global_limit=event_bus_config['global_rate_limit'])
                if 'per_event_rate_limit' in event_bus_config:
                    self.event_bus.update_rate_limits(per_event_limit=event_bus_config['per_event_rate_limit'])
                self.logger.info("event_bus_rate_limit_config_success")
        except Exception as e:
            self.logger.error("event_bus_init_fail", exc=e)

        # 7. 动作调度器
        self.action_dispatcher = global_dispatcher

        # 8. 预设模块管理器为空（主控初始化后注入）
        self.module_manager: Optional[ModuleManager] = None

        # 9. 配置热更新自动限流
        self.config_manager.register_callback('event_bus', self._update_event_bus_config)

        self.logger.info('context_initialized', mode='开发' if dev_mode else '生产')

    # ---- 权限体系配置 ----
    def _init_access_control(self) -> AccessControl:
        ac = AccessControl()
        try:
            roles_config = self.config_manager.get('access_control_roles', {})
            for role_name, permissions in roles_config.items():
                ac.add_role(role_name, permissions)
            event_perms = self.config_manager.get('event_permissions', {})
            for event_type, perm in event_perms.items():
                ac.event_permissions[event_type] = perm
        except Exception as e:
            self.logger.error("access_control_init_error", exc=e)
        return ac

    # ---- 事件总线限流配置变更热更新 ----
    def _update_event_bus_config(self, key: str, value: Any) -> None:
        if key != 'event_bus' or not self.event_bus:
            return
        try:
            if hasattr(self.event_bus, 'update_rate_limits'):
                if 'global_rate_limit' in value:
                    self.event_bus.update_rate_limits(global_limit=value['global_rate_limit'])
                if 'per_event_rate_limit' in value:
                    self.event_bus.update_rate_limits(per_event_limit=value['per_event_rate_limit'])
            self.logger.info("event_bus_rate_limit_updated")
        except Exception as e:
            self.logger.error("event_bus_rate_limit_update_error", exc=e)

    # ---- 服务注册与权限风控 ----
    def register_service(self, name: str, service: Any, role: str = 'system') -> bool:
        if not self.access_control.check_permission(role, 'service.register'):
            self.logger.warning('service_registration_denied', service=name, role=role)
            return False
        if name in self.services:
            self.logger.warning('service_already_registered', name=name)
            return False
        self.services[name] = service
        self.logger.info('service_registered', service=name)
        return True

    def get_service(self, name: str) -> Optional[Any]:
        return self.services.get(name)

    # ---- 配置管理接口 ----
    def get_config(self, key: str, default: Any = None, module: Optional[str] = None) -> Any:
        return self.config_manager.get(key, default, module)

    def update_config(self, key: str, value: Any, module: Optional[str] = None, requester_role: str = 'system') -> bool:
        if not self.access_control.check_permission(requester_role, 'config.update'):
            self.logger.warning('config_update_denied', key=key, role=requester_role)
            return False
        self.config_manager.set(key, value, auto_save=True)
        return True

    # ---- 动作调度分发便捷接口 ----
    def register_action(self, name: str, **options):
        return self.action_dispatcher.register_action(name, **options)

    def execute_action(self, name: str, *args, **kwargs):
        """
        Legacy compat 入口：保留旧式位置参数调用，直达 dispatcher.execute(...)。
        新 live 主链应优先使用 call_action(name, params=...)。
        """
        return self.action_dispatcher.execute(name, *args, **kwargs)

    def call_action(self, name: str, *args, **kwargs):
        """
        标准动作调用入口。
        统一口径：context.call_action(name, params=..., **kwargs)
        -> dispatcher.call_action(name, params=params, **kwargs)
        """
        dispatcher = self.action_dispatcher

        params = kwargs.pop("params", None)
        if args:
            raise TypeError(
                "SystemContext.call_action 仅支持 params=dict 标准口径；"
                "旧式位置参数请使用 execute_action(...)"
            )

        if params is not None and not isinstance(params, dict):
            raise TypeError("SystemContext.call_action 的 params 必须是 dict 或 None")

        caller = getattr(dispatcher, "call_action", None)
        if not callable(caller):
            raise AttributeError("action_dispatcher 缺少标准 call_action(name, params=...) 接口")
        return caller(name, params=params, **kwargs)

    def list_actions(self, module: Optional[str] = None, detailed: bool = False):
        """
        标准动作发现入口。
        统一口径：context.list_actions(module=None, detailed=False)
        -> dispatcher.list_actions(...).
        缺少 dispatcher 或 list_actions 时返回空列表，供 GUI/fake context 安全降级。
        """
        dispatcher = getattr(self, "action_dispatcher", None)
        lister = getattr(dispatcher, "list_actions", None)
        if not callable(lister):
            return []

        try:
            return lister(module=module, detailed=detailed)
        except TypeError:
            if module is not None:
                return lister(module)
            try:
                return lister(detailed=detailed)
            except TypeError:
                return lister()

    def get_system_health(self) -> Dict[str, Any]:
        """
        标准系统健康读取入口。
        统一口径：context.get_system_health() -> module_manager.health_check()。
        缺少 module_manager 或 health_check 时返回稳定降级结构。
        """
        module_manager = getattr(self, "module_manager", None)
        health_check = getattr(module_manager, "health_check", None)
        if not callable(health_check):
            return {"status": "unknown", "health": "UNKNOWN", "modules": {}}
        try:
            result = health_check()
        except Exception as e:
            return {"status": "unknown", "health": "UNKNOWN", "modules": {}, "error": str(e)}
        if isinstance(result, dict):
            result.setdefault("modules", {})
            return result
        return {"status": "unknown", "health": "UNKNOWN", "modules": {}, "raw": result}

    def get_system_status(self) -> Dict[str, Any]:
        """
        轻量系统状态快照读取入口。
        统一口径：context.get_system_status()。
        仅返回 status / system_running / uptime / modules_loaded。
        缺少 start_time / module_manager / loaded_modules 时稳定降级。
        """
        system_running = bool(getattr(self, "system_running", False))
        start_time = getattr(self, "start_time", None)
        if isinstance(start_time, (int, float)):
            uptime = max(0.0, time.time() - start_time)
        else:
            uptime = 0.0

        module_manager = getattr(self, "module_manager", None)
        loaded_modules = getattr(module_manager, "loaded_modules", None)
        if isinstance(loaded_modules, dict):
            modules_loaded = len(loaded_modules)
        elif isinstance(loaded_modules, (list, tuple, set)):
            modules_loaded = len(loaded_modules)
        else:
            modules_loaded = 0

        return {
            "status": "RUNNING" if system_running else "UNKNOWN",
            "system_running": system_running,
            "uptime": uptime,
            "modules_loaded": modules_loaded,
        }

    def get_loaded_modules(self) -> list[str]:
        """
        模块清单读取入口。
        统一口径：context.get_loaded_modules()。
        优先走 module_manager.list_all_modules()，否则降级到 loaded_modules。
        缺少 module_manager / loaded_modules 时返回空列表。
        """
        module_manager = getattr(self, "module_manager", None)
        list_all_modules = getattr(module_manager, "list_all_modules", None)
        if callable(list_all_modules):
            try:
                result = list_all_modules()
                if isinstance(result, (list, tuple, set)):
                    return [str(x) for x in result]
            except Exception:
                pass

        loaded_modules = getattr(module_manager, "loaded_modules", None)
        if isinstance(loaded_modules, dict):
            return [str(x) for x in loaded_modules.keys()]
        if isinstance(loaded_modules, (list, tuple, set)):
            return [str(x) for x in loaded_modules]
        return []

    # ---- 🌸 权限+安全风控统一校验接口 ----
    def check_access(self, module: str, action: str, user: str = "system", context: dict = None) -> bool:
        """安全风控+权限组合校验（建议所有业务均统一走此接口！）"""
        allowed, reason = self.security_manager.check_access(module, action, user, context)
        if not allowed:
            self.logger.warning(f"access_denied [{module}.{action}] {reason}")
        return allowed

    # ---- 事件总线健康指标接口 ----
    def get_event_bus_metrics(self) -> dict:
        if self.event_bus and hasattr(self.event_bus, "get_metrics"):
            return self.event_bus.get_metrics()
        return {}

    def cleanup(self):
        # 可按需扩展，资源释放、日志收尾等
        self.logger.info('context_cleanup')

__all__ = ['SystemContext']
