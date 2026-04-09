# utils/trace_logger.py
"""
企业级跟踪日志系统
支持多级日志、日志轮转和请求跟踪
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
import threading
import uuid

class TraceLogger(logging.Logger):
    """增强型日志记录器，支持请求跟踪"""
    
    _loggers = {}
    _lock = threading.Lock()
    _default_level = logging.INFO
    
    def __init__(self, name):
        super().__init__(name)
        self.propagate = False
        self.setLevel(self._default_level)
        
        # 添加控制台处理器
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.addHandler(console_handler)
        
        # 默认的请求ID
        self.request_id = str(uuid.uuid4())[:8]
        
    def set_request_id(self, request_id: str):
        """设置当前请求ID"""
        self.request_id = request_id
        
    @classmethod
    def get_logger(cls, name: str) -> "TraceLogger":
        """获取或创建日志记录器"""
        with cls._lock:
            if name not in cls._loggers:
                cls._loggers[name] = TraceLogger(name)
            return cls._loggers[name]
    
    @classmethod
    def set_default_level(cls, level: str):
        """设置默认日志级别"""
        level = level.upper()
        if level == "DEBUG":
            cls._default_level = logging.DEBUG
        elif level == "INFO":
            cls._default_level = logging.INFO
        elif level == "WARNING":
            cls._default_level = logging.WARNING
        elif level == "ERROR":
            cls._default_level = logging.ERROR
        elif level == "CRITICAL":
            cls._default_level = logging.CRITICAL
        else:
            print(f"未知日志级别: {level}, 使用默认级别 INFO")
            cls._default_level = logging.INFO
            
        # 更新所有现有记录器的级别
        for logger in cls._loggers.values():
            logger.setLevel(cls._default_level)
    
    def add_file_handler(self, log_dir: str = "logs", max_bytes: int = 10*1024*1024, backup_count: int = 5):
        """添加文件日志处理器"""
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{self.name}_{datetime.now().strftime('%Y%m%d')}.log")
        
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
        )
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        self.addHandler(file_handler)
    
    def _log_with_request_id(self, level, msg, args, exc_info=None, extra=None, stack_info=False):
        """添加请求ID到日志记录"""
        if extra is None:
            extra = {}
        extra['request_id'] = self.request_id
        super().log(level, msg, args, exc_info, extra, stack_info)
    
    def debug(self, msg, *args, **kwargs):
        self._log_with_request_id(logging.DEBUG, msg, args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        self._log_with_request_id(logging.INFO, msg, args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self._log_with_request_id(logging.WARNING, msg, args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        self._log_with_request_id(logging.ERROR, msg, args, **kwargs)
    
    def critical(self, msg, *args, **kwargs):
        self._log_with_request_id(logging.CRITICAL, msg, args, **kwargs)

# 全局日志记录器快捷方式
def get_logger(name: str) -> TraceLogger:
    return TraceLogger.get_logger(name)
