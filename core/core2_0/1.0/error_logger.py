import os
import logging
from datetime import datetime
import traceback
from pathlib import Path
from typing import Optional, Dict, Any
import json
import inspect
import sys

class ErrorLogger:
    """增强型错误日志记录器"""
    
    def __init__(
        self,
        log_dir: str = "logs/errors",
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        max_backup_count: int = 30,
        log_to_console: bool = True,
        json_format: bool = False
    ):
        """
        初始化错误日志记录器
        
        参数:
            log_dir: 日志目录路径
            max_file_size: 单个日志文件最大大小(字节)
            max_backup_count: 最大备份文件数
            log_to_console: 是否同时输出到控制台
            json_format: 是否使用JSON格式记录
        """
        self.log_dir = Path(log_dir)
        self.max_file_size = max_file_size
        self.max_backup_count = max_backup_count
        self.log_to_console = log_to_console
        self.json_format = json_format
        
        # 确保日志目录存在
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化日志记录器
        self._init_logger()
    
    def _init_logger(self) -> None:
        """初始化日志记录器配置"""
        self.logger = logging.getLogger("ErrorLogger")
        self.logger.setLevel(logging.ERROR)
        
        # 移除所有已有的处理器
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # 添加文件处理器
        file_handler = self._get_file_handler()
        self.logger.addHandler(file_handler)
        
        # 可选的控制台输出
        if self.log_to_console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(self._get_formatter())
            self.logger.addHandler(console_handler)
    
    def _get_file_handler(self) -> logging.Handler:
        """获取文件处理器"""
        handler = logging.handlers.RotatingFileHandler(
            filename=self.log_dir / "error.log",
            maxBytes=self.max_file_size,
            backupCount=self.max_backup_count,
            encoding="utf-8"
        )
        handler.setFormatter(self._get_formatter())
        return handler
    
    def _get_formatter(self) -> logging.Formatter:
        """获取日志格式化器"""
        if self.json_format:
            return JsonFormatter()
        return logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    def _get_caller_info(self) -> Dict[str, Any]:
        """获取调用者信息"""
        frame = inspect.currentframe()
        try:
            # 向上回溯3帧以找到实际调用者
            for _ in range(3):
                if frame.f_back:
                    frame = frame.f_back
            
            return {
                "file": frame.f_code.co_filename,
                "line": frame.f_lineno,
                "function": frame.f_code.co_name,
                "module": inspect.getmodule(frame).__name__ if inspect.getmodule(frame) else None
            }
        finally:
            del frame  # 避免引用循环
    
    def log_error(
        self,
        error: Exception,
        context: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        level: str = "ERROR"
    ) -> None:
        """
        记录错误信息
        
        参数:
            error: 异常对象
            context: 错误上下文说明
            extra_data: 额外记录的数据
            level: 日志级别(ERROR/WARNING/CRITICAL等)
        """
        log_level = getattr(logging, level.upper(), logging.ERROR)
        
        caller_info = self._get_caller_info()
        exc_info = sys.exc_info()
        
        extra = {
            "caller": caller_info,
            "context": context,
            "extra_data": extra_data,
            "traceback": traceback.format_exc(),
            "exception_type": error.__class__.__name__,
            "exception_msg": str(error)
        }
        
        self.logger.log(
            log_level,
            f"{error.__class__.__name__}: {str(error)}",
            exc_info=exc_info,
            extra={"error_details": extra}
        )
    
    def log_manual(
        self,
        message: str,
        level: str = "ERROR",
        context: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        手动记录错误信息(非异常情况)
        
        参数:
            message: 错误消息
            level: 日志级别
            context: 错误上下文
            extra_data: 额外数据
        """
        log_level = getattr(logging, level.upper(), logging.ERROR)
        caller_info = self._get_caller_info()
        
        extra = {
            "caller": caller_info,
            "context": context,
            "extra_data": extra_data,
            "traceback": "".join(traceback.format_stack(limit=10)),
            "exception_type": None,
            "exception_msg": message
        }
        
        self.logger.log(
            log_level,
            message,
            extra={"error_details": extra}
        )


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON字符串"""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "pathname": record.pathname,
            "lineno": record.lineno,
            "funcName": record.funcName,
        }
        
        if hasattr(record, "error_details"):
            log_data.update(record.error_details)
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False, indent=2)


# 全局单例实例
error_logger = ErrorLogger(
    log_dir="logs/errors",
    max_file_size=10 * 1024 * 1024,  # 10MB
    max_backup_count=30,
    log_to_console=True,
    json_format=False
)

def log_error(
    error: Exception,
    context: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    level: str = "ERROR"
) -> None:
    """记录错误的便捷函数"""
    error_logger.log_error(error, context, extra_data, level)

def log_manual(
    message: str,
    level: str = "ERROR",
    context: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None
) -> None:
    """手动记录错误的便捷函数"""
    error_logger.log_manual(message, level, context, extra_data)
