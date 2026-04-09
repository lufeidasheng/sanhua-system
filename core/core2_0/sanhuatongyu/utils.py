import time
import random
import asyncio
from functools import wraps
from typing import Callable, TypeVar, Any, cast
from core.core2_0.sanhuatongyu.logger import get_logger

logger = get_logger('utils')

F = TypeVar('F', bound=Callable[..., Any])

def exponential_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    log_errors: bool = True
) -> Callable[[F], F]:
    """
    指数退避重试装饰器（支持同步/异步函数）
    - max_retries: 最大重试次数
    - base_delay: 初始重试间隔（秒）
    - max_delay: 最大重试间隔（秒）
    - log_errors: 是否记录重试/异常日志
    """
    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                attempt = 0
                while attempt <= max_retries:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        attempt += 1
                        if attempt > max_retries:
                            if log_errors:
                                logger.error(
                                    "max_retries_exceeded",
                                    function=func.__name__,
                                    extra={"error": str(e)}
                                )
                            raise
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        if log_errors:
                            logger.warning(
                                "retrying_after_failure",
                                function=func.__name__,
                                attempt=attempt,
                                delay=round(delay, 2),
                                error=str(e)
                            )
                        await asyncio.sleep(delay)
            return cast(F, async_wrapper)
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                attempt = 0
                while attempt <= max_retries:
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        attempt += 1
                        if attempt > max_retries:
                            if log_errors:
                                logger.error(
                                    "max_retries_exceeded",
                                    function=func.__name__,
                                    extra={"error": str(e)}
                                )
                            raise
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        if log_errors:
                            logger.warning(
                                "retrying_after_failure",
                                function=func.__name__,
                                attempt=attempt,
                                delay=round(delay, 2),
                                error=str(e)
                            )
                        time.sleep(delay)
            return cast(F, sync_wrapper)
    return decorator

# ==== 其他实用工具举例 ====
def safe_import(module_name: str, class_name: str = None):
    """
    安全导入模块/类
    """
    try:
        module = __import__(module_name, fromlist=[class_name] if class_name else [])
        return getattr(module, class_name) if class_name else module
    except (ImportError, AttributeError):
        logger.warning("safe_import_failed", module=module_name, class_name=class_name)
        return None
