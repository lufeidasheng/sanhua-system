"""
三花聚顶 · 企业级增强日志系统
支持：多语言(i18n)、结构化日志、请求追踪、异常链路、按天轮转、多格式输出
"""

import json
import logging
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, Tuple
from logging.handlers import TimedRotatingFileHandler
from contextlib import contextmanager

# ==== 国际化支持（死锁免疫、锁外IO） ====
class I18nManager:
    """国际化管理器，支持动态加载多语言资源（多线程/死锁安全）"""
    _translations: Dict[str, Dict[str, str]] = {}
    _current_lang: str = 'zh_CN'
    _lock = threading.Lock()
    _i18n_dir = Path(__file__).parent / 'i18n'

    @classmethod
    def set_language(cls, lang: str, i18n_dir: Optional[Union[str, Path]] = None) -> bool:
        base_dir = Path(i18n_dir) if i18n_dir else cls._i18n_dir
        trans_file = base_dir / f'{lang}.json'
        trans_data = None
        if trans_file.exists():
            try:
                trans_data = json.loads(trans_file.read_text(encoding='utf-8'))
            except Exception as e:
                print(f"[I18n] 加载语言文件失败: {e}", file=sys.stderr)
                return False
        else:
            print(f"[I18n] 语言包文件不存在: {trans_file}", file=sys.stderr)
            return False

        with cls._lock:
            cls._translations[lang] = trans_data or {}
            cls._current_lang = lang
        return True

    @classmethod
    def get_text(cls, key: str, **kwargs) -> str:
        lang = cls._current_lang
        if lang not in cls._translations:
            loaded = cls.set_language(lang)
            if not loaded:
                return key
        with cls._lock:
            template = cls._translations.get(lang, {}).get(key, key)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

# ==== 日志格式化器 ====
class EnhancedJsonFormatter(logging.Formatter):
    """增强型JSON格式化器，支持完整异常信息和上下文"""
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "thread": record.threadName,
            "trace_id": getattr(record, 'trace_id', 'system'),
            "file": f"{record.pathname}:{record.lineno}",
            "function": record.funcName,
        }
        if record.exc_info:
            exc_type, exc_val, exc_tb = record.exc_info
            if exc_type:
                log_entry["exception"] = {
                    "type": exc_type.__name__,
                    "message": str(exc_val),
                    "stack": ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
                }
        if hasattr(record, "context"):
            log_entry.update(record.context)
        return json.dumps(log_entry, ensure_ascii=False, indent=2)

class EnhancedFormatter(logging.Formatter):
    """增强型普通格式化器，保证trace_id/module_name安全存在"""
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, 'trace_id'):
            record.trace_id = 'system'
        if not hasattr(record, 'module_name'):
            record.module_name = record.name
        return super().format(record)

# ==== 企业级日志类 ====
class EnterpriseLogger:
    """
    企业级日志记录器
    特性：
    - 多语言支持
    - 请求追踪
    - 结构化日志
    - 多格式输出
    - 线程安全
    """
    _loggers: Dict[str, 'EnterpriseLogger'] = {}
    _lock = threading.Lock()
    _default_level = logging.INFO
    _configured = False

    def __init__(self, name: str):
        self.name = name
        self._logger = logging.getLogger(name)
        self._logger.setLevel(self._default_level)
        self._logger.propagate = False
        self._local = threading.local()
        self._local.trace_id = f"sys-{uuid.uuid4().hex[:8]}"
        self._local.context = {}

    @property
    def trace_id(self) -> str:
        """获取当前请求的跟踪ID"""
        return getattr(self._local, 'trace_id', 'system')

    @trace_id.setter
    def trace_id(self, value: str):
        self._local.trace_id = value

    @classmethod
    def get_logger(cls, name: str) -> 'EnterpriseLogger':
        with cls._lock:
            if name not in cls._loggers:
                cls._loggers[name] = EnterpriseLogger(name)
            return cls._loggers[name]

    @classmethod
    def configure(
        cls,
        level: str = "INFO",
        log_dir: str = "logs",
        console_format: Optional[str] = None,
        json_format: bool = True,
        i18n_lang: str = "zh_CN",
        i18n_dir: Optional[str] = None,
    ):
        if cls._configured:
            return
        cls._configured = True
        # 设置日志级别
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        cls._default_level = level_map.get(level.upper(), logging.INFO)
        # 设置国际化（提前加载，避免首次日志死锁）
        I18nManager.set_language(i18n_lang, i18n_dir)
        # 创建日志目录
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)
        default_format = '[%(asctime)s] [%(trace_id)s] [%(module_name)s] %(levelname)s - %(message)s'
        formatter = EnhancedFormatter(console_format or default_format)
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        # 按天轮转文件处理器
        file_handler = TimedRotatingFileHandler(
            log_path / "application.log",
            when='midnight',
            backupCount=15,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        # JSON文件处理器
        json_handler = TimedRotatingFileHandler(
            log_path / "application.json.log",
            when='midnight',
            backupCount=15,
            encoding='utf-8'
        )
        json_handler.setFormatter(EnhancedJsonFormatter())
        # 配置根日志记录器
        root = logging.getLogger()
        root.setLevel(cls._default_level)
        root.handlers.clear()
        root.addHandler(console_handler)
        root.addHandler(file_handler)
        if json_format:
            root.addHandler(json_handler)
        for logger in cls._loggers.values():
            logger._logger.setLevel(cls._default_level)

    @contextmanager
    def with_trace_id(self, trace_id: str):
        old_id = getattr(self._local, 'trace_id', None)
        self._local.trace_id = trace_id
        try:
            yield
        finally:
            self._local.trace_id = old_id

    def _log(
        self,
        level: int,
        key: str,
        extra_data: Optional[Dict[str, Any]] = None,
        exc_info: Optional[Union[bool, Tuple[type, BaseException, Any]]] = None,
        **kwargs
    ):
        message = I18nManager.get_text(key, **kwargs)
        context = {
            **getattr(self._local, 'context', {}),
            **(extra_data or {})
        }
        # 兼容 exc_info 可能为 True/False 或 三元组
        log_exc_info = None
        if isinstance(exc_info, tuple):
            exc_type, exc_val, exc_tb = exc_info
            if exc_type:
                context.update({
                    'exception_type': exc_type.__name__,
                    'exception_msg': str(exc_val),
                    'stack_trace': ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
                })
                log_exc_info = exc_info
        elif exc_info is True:
            # 直接传 True 让 logging 捕获当前异常栈
            log_exc_info = True
        # 如果 exc_info 是 False 或 None，什么也不传

        self._logger.log(
            level,
            message,
            extra={
                'trace_id': self.trace_id,
                'module_name': self.name,
                'context': context
            },
            exc_info=log_exc_info
        )

    def debug(self, key: str, **kwargs):
        self._log(logging.DEBUG, key, **kwargs)

    def info(self, key: str, **kwargs):
        self._log(logging.INFO, key, **kwargs)

    def warning(self, key: str, **kwargs):
        self._log(logging.WARNING, key, **kwargs)

    def error(self, key: str, exc: Optional[Exception] = None, **kwargs):
        exc_info = sys.exc_info() if exc is None else (type(exc), exc, exc.__traceback__)
        self._log(logging.ERROR, key, exc_info=exc_info, **kwargs)

    def critical(self, key: str, exc: Optional[Exception] = None, **kwargs):
        exc_info = sys.exc_info() if exc is None else (type(exc), exc, exc.__traceback__)
        self._log(logging.CRITICAL, key, exc_info=exc_info, **kwargs)

    def log_exception(self, key: str, exc: Exception, **kwargs):
        self._log(logging.ERROR, key, exc_info=(type(exc), exc, exc.__traceback__), **kwargs)

    def bind(self, **kwargs):
        if not hasattr(self._local, 'context'):
            self._local.context = {}
        self._local.context.update(kwargs)

# 兼容旧链路：历史模块仍会直接导入/实例化 TraceLogger。
# 保留同名导出，避免启动期因 import TraceLogger 失败而中断。
class TraceLogger(EnterpriseLogger):
    pass

# ==== 全局快捷访问 ====
def get_logger(name: str = "application") -> EnterpriseLogger:
    return EnterpriseLogger.get_logger(name)

def configure_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    console_format: Optional[str] = None,
    json_format: bool = True,
    i18n_lang: str = "zh_CN",
    i18n_dir: Optional[str] = None,
):
    EnterpriseLogger.configure(
        level=level,
        log_dir=log_dir,
        console_format=console_format,
        json_format=json_format,
        i18n_lang=i18n_lang,
        i18n_dir=i18n_dir,
    )

__all__ = [
    "EnterpriseLogger",
    "TraceLogger",
    "get_logger",
    "configure_logging",
    "I18nManager"
]
