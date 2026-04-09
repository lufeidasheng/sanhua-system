import os
import yaml
from typing import Any, Callable, Optional
from .logger import get_logger  # 🚩 引入新日志
import logging  # 兼容老代码异常打印（可考虑移除）

class ConfigManager:
    """多层配置管理系统（三花聚顶专用）"""

    def __init__(self, global_path: str, user_path: str = None):
        self.logger = get_logger('config')  # 🌸 新日志系统
        self.global_config = {}
        self.module_configs = {}
        self.user_configs = {}
        self.callbacks = {}

        # 使用新的容错加载方法
        self.global_config = self.load_config(global_path)
        self.user_configs = self.load_config(user_path) if user_path else {}

        # 初始化模块配置
        self.module_configs = self.global_config.get('modules', {})

    def load_config(self, path: str) -> dict:
        """安全加载配置文件，路径不存在时创建默认配置文件"""
        try:
            if not path or not os.path.exists(path):
                default_config = {"modules": {}, "system": {}}
                if path:  # 确保路径不为None再尝试创建目录和文件
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'w', encoding='utf-8') as f:
                        yaml.safe_dump(default_config, f)
                    self.logger.info("config_default_created", path=path)
                return default_config

            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                self.logger.info("config_loaded", path=path)
                return config
        except Exception as e:
            self.logger.error("config_load_failed", path=path, error=str(e))
            logging.error(f"Config load failed: {str(e)}")
            return {"modules": {}, "system": {}}

    def load_configs(self, global_path: str, user_path: str):
        """此方法保留但内部不再使用，兼容老代码"""
        pass  # 直接用构造函数里load_config的结果替代

    def get(self, key: str, default=None, module: str = None) -> Any:
        # 模块特定配置优先
        if module and module in self.module_configs and key in self.module_configs[module]:
            return self.module_configs[module][key]

        # 用户配置其次
        if key in self.user_configs:
            return self.user_configs[key]

        # 全局配置最后
        return self.global_config.get(key, default)

    def update_config(self, key: str, value: Any, module: str = None):
        if module:
            if module not in self.module_configs:
                self.module_configs[module] = {}
            self.module_configs[module][key] = value
        else:
            self.user_configs[key] = value

        self.trigger_update(key, module)

    def register_callback(self, key: str, callback: Callable, module: str = None):
        identifier = f"{module}:{key}" if module else key
        if identifier not in self.callbacks:
            self.callbacks[identifier] = []
        self.callbacks[identifier].append(callback)

    def trigger_update(self, key: str, module: str = None):
        identifier = f"{module}:{key}" if module else key
        for callback in self.callbacks.get(identifier, []):
            try:
                callback(key, self.get(key, module=module))
            except Exception as e:
                self.logger.error(
                    "config_callback_failed",
                    key=key, error=str(e)
                )
