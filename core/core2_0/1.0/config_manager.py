import yaml
import os
import threading
import time
from copy import deepcopy
import logging
from typing import Any, Optional, Dict, Callable, List
from pathlib import Path

class ConfigManager:
    def __init__(
        self,
        default_config_path: str = "default_config.yaml",
        user_config_path: str = "config.yaml",
        auto_reload: bool = True,
        reload_interval: int = 5,
        env_prefix: str = "APP_",
    ):
        """
        初始化配置管理器
        
        参数:
            default_config_path: 默认配置文件路径
            user_config_path: 用户配置文件路径
            auto_reload: 是否自动重载配置文件
            reload_interval: 配置文件检查间隔(秒)
            env_prefix: 环境变量前缀
        """
        self.default_config_path = Path(default_config_path)
        self.user_config_path = Path(user_config_path)
        self.auto_reload = auto_reload
        self.reload_interval = reload_interval
        self.env_prefix = env_prefix
        
        # 线程安全相关
        self._config_lock = threading.RLock()
        self._config = {}
        self._last_mtime = 0
        self._stop_reload = False
        self._change_callbacks = []
        
        # 日志配置
        self.logger = logging.getLogger("ConfigManager")
        self.logger.setLevel(logging.INFO)
        
        # 初始化加载
        self.load_config()
        
        # 启动自动重载线程
        if self.auto_reload:
            self._reload_thread = threading.Thread(
                target=self._watch_config_file,
                daemon=True,
                name="ConfigReloadThread"
            )
            self._reload_thread.start()

    def _merge_dict(self, base: dict, override: dict) -> dict:
        """递归合并字典，override优先"""
        result = deepcopy(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._merge_dict(result[k], v)
            else:
                result[k] = v
        return result

    def _load_from_env(self) -> dict:
        """从环境变量加载配置"""
        env_config = {}
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                # 转换环境变量名称为配置路径 (APP_DB_HOST -> db.host)
                config_key = key[len(self.env_prefix):].lower()
                keys = config_key.split("_")
                
                # 尝试转换值类型
                try:
                    if value.lower() in ("true", "false"):
                        parsed_value = value.lower() == "true"
                    elif value.isdigit():
                        parsed_value = int(value)
                    elif value.replace(".", "", 1).isdigit():
                        parsed_value = float(value)
                    else:
                        parsed_value = value
                except (ValueError, AttributeError):
                    parsed_value = value
                
                # 构建嵌套字典
                current = env_config
                for k in keys[:-1]:
                    if k not in current:
                        current[k] = {}
                    current = current[k]
                current[keys[-1]] = parsed_value
        return env_config

    def load_yaml(self, path: Path) -> dict:
        """加载YAML配置文件"""
        if not path.exists():
            self.logger.warning(f"配置文件 {path} 不存在")
            return {}
        
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else {}
        except yaml.YAMLError as e:
            self.logger.error(f"加载配置文件 {path} 出错 (YAML格式错误): {e}")
            return {}
        except Exception as e:
            self.logger.error(f"加载配置文件 {path} 出错: {e}")
            return {}

    def load_config(self) -> None:
        """加载并合并所有配置源"""
        default_cfg = self.load_yaml(self.default_config_path)
        user_cfg = self.load_yaml(self.user_config_path)
        env_cfg = self._load_from_env()
        
        with self._config_lock:
            # 合并顺序: 默认配置 <- 用户配置 <- 环境变量
            merged = self._merge_dict(default_cfg, user_cfg)
            self._config = self._merge_dict(merged, env_cfg)
        
        self._update_mtime()
        self._notify_change()
        self.logger.info("配置加载完成")

    def _update_mtime(self) -> None:
        """更新文件修改时间记录"""
        try:
            mtime = os.path.getmtime(self.user_config_path)
            self._last_mtime = mtime
        except Exception as e:
            self.logger.warning(f"获取文件修改时间失败: {e}")
            self._last_mtime = 0

    def _watch_config_file(self) -> None:
        """监控配置文件变化的线程函数"""
        while not self._stop_reload:
            try:
                mtime = os.path.getmtime(self.user_config_path)
                if mtime != self._last_mtime:
                    self.logger.info("发现配置文件变更，重新加载")
                    self.load_config()
                self._last_mtime = mtime
            except Exception as e:
                self.logger.warning(f"监控配置文件出错: {e}")
            time.sleep(self.reload_interval)

    def _notify_change(self) -> None:
        """通知所有注册的回调函数"""
        with self._config_lock:
            config_copy = deepcopy(self._config)
        
        for callback in self._change_callbacks:
            try:
                callback(config_copy)
            except Exception as e:
                self.logger.error(f"配置变更回调执行失败: {e}")

    def register_change_callback(self, callback: Callable[[Dict], None]) -> None:
        """注册配置变更回调函数"""
        with self._config_lock:
            self._change_callbacks.append(callback)

    def get(self, key: Optional[str] = None, default: Any = None) -> Any:
        """
        获取配置值
        
        参数:
            key: 点分隔的配置键名 (如 "db.host"), None表示获取全部配置
            default: 键不存在时返回的默认值
        """
        with self._config_lock:
            if key is None:
                return deepcopy(self._config)
            
            keys = key.split(".")
            val = self._config
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return deepcopy(val)

    def set(self, key: str, value: Any, auto_save: bool = False) -> None:
        """
        设置配置值
        
        参数:
            key: 点分隔的配置键名
            value: 要设置的值
            auto_save: 是否自动保存到用户配置文件
        """
        with self._config_lock:
            keys = key.split(".")
            d = self._config
            for k in keys[:-1]:
                if k not in d or not isinstance(d[k], dict):
                    d[k] = {}
                d = d[k]
            d[keys[-1]] = value
        
        self._notify_change()
        
        if auto_save:
            self.save_config()

    def save_config(self, path: Optional[Path] = None) -> bool:
        """
        保存配置到文件
        
        参数:
            path: 保存路径，None表示使用用户配置文件路径
        返回:
            是否保存成功
        """
        if path is None:
            path = self.user_config_path
        
        with self._config_lock:
            config_to_save = deepcopy(self._config)
            
        try:
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(
                    config_to_save,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False
                )
            self.logger.info(f"配置已保存到 {path}")
            self._update_mtime()
            return True
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            return False

    def stop(self) -> None:
        """停止配置管理器"""
        self._stop_reload = True
        if hasattr(self, "_reload_thread") and self._reload_thread.is_alive():
            self._reload_thread.join(timeout=2)
        self.logger.info("配置管理器已停止")


# 全局单例实例
config_manager = ConfigManager()

def load_config() -> None:
    """重新加载配置 (便捷函数)"""
    config_manager.load_config()
