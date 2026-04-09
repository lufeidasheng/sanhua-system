from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)
"""
core.core2_0/utils.py
实用工具函数
"""
import time
import logging
from functools import wraps

def exponential_backoff(max_retries=3, base_delay=1, max_delay=30):
    """
    指数退避装饰器
    :param max_retries: 最大重试次数
    :param base_delay: 基础延迟时间（秒）
    :param max_delay: 最大延迟时间（秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            delay = base_delay
            
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                        
                    # 计算下一次延迟时间
                    delay = min(delay * 2, max_delay)
                    log.warning(f"Operation failed (retry {retries}/{max_retries}), "
                                  f"retrying in {delay:.1f}s. Error: {str(e)}")
                    time.sleep(delay)
                    
            return func(*args, **kwargs)  # 最后一次尝试
        return wrapper
    return decorator

# 添加其他可能需要的实用函数
def safe_import(module_name, class_name=None):
    """
    安全导入模块或类
    :param module_name: 模块名
    :param class_name: 类名（可选）
    """
    try:
        module = __import__(module_name, fromlist=[class_name] if class_name else [])
        return getattr(module, class_name) if class_name else module
    except (ImportError, AttributeError):
        return None
