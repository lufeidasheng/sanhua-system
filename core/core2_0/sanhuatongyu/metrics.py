"""
core.core2_0/sanhuatongyu/monitoring/metrics.py
三花聚顶 · Prometheus 监控指标导出器
"""
import time
from typing import Dict, Any, Optional
from prometheus_client import start_http_server, Counter, Gauge, Histogram

from core.core2_0.sanhuatongyu.logger import get_logger

class PrometheusExporter:
    """Prometheus 监控导出器实现"""
    
    def __init__(self, port: int = 8000):
        self.logger = get_logger("metrics")
        self.port = port
        self.metrics: Dict[str, Any] = {}
        
        try:
            start_http_server(self.port)
            self.logger.info("metrics_prometheus_server_started", port=self.port)
        except Exception as e:
            self.logger.error("metrics_prometheus_server_failed", error=str(e))
    
    def register_counter(self, name: str, description: str, labels: Optional[list] = None):
        """注册计数器指标"""
        if name in self.metrics:
            self.logger.warning("metrics_metric_already_registered", name=name)
            return
        self.metrics[name] = Counter(name, description, labels or [])
        self.logger.debug("metrics_counter_registered", name=name)
    
    def register_gauge(self, name: str, description: str, labels: Optional[list] = None):
        """注册测量指标"""
        if name in self.metrics:
            self.logger.warning("metrics_metric_already_registered", name=name)
            return
        self.metrics[name] = Gauge(name, description, labels or [])
        self.logger.debug("metrics_gauge_registered", name=name)
    
    def register_histogram(self, name: str, description: str, buckets: list, labels: Optional[list] = None):
        """注册直方图指标"""
        if name in self.metrics:
            self.logger.warning("metrics_metric_already_registered", name=name)
            return
        self.metrics[name] = Histogram(name, description, labels or [], buckets=buckets)
        self.logger.debug("metrics_histogram_registered", name=name)
    
    def increment(self, name: str, value: float = 1, labels: Optional[dict] = None):
        """增加计数器"""
        if name not in self.metrics:
            self.logger.error("metrics_metric_not_registered", name=name)
            return
        try:
            metric = self.metrics[name]
            if labels:
                metric.labels(**labels).inc(value)
            else:
                metric.inc(value)
        except Exception as e:
            self.logger.error("metrics_increment_failed", name=name, error=str(e))
    
    def set_value(self, name: str, value: float, labels: Optional[dict] = None):
        """设置测量值"""
        if name not in self.metrics:
            self.logger.error("metrics_metric_not_registered", name=name)
            return
        try:
            metric = self.metrics[name]
            if labels:
                metric.labels(**labels).set(value)
            else:
                metric.set(value)
        except Exception as e:
            self.logger.error("metrics_set_value_failed", name=name, error=str(e))
    
    def observe(self, name: str, value: float, labels: Optional[dict] = None):
        """记录直方图观察值"""
        if name not in self.metrics:
            self.logger.error("metrics_metric_not_registered", name=name)
            return
        try:
            metric = self.metrics[name]
            if labels:
                metric.labels(**labels).observe(value)
            else:
                metric.observe(value)
        except Exception as e:
            self.logger.error("metrics_observe_failed", name=name, error=str(e))
    
    def time_function(self, name: str, labels: Optional[dict] = None):
        """函数执行时间测量装饰器"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start_time
                try:
                    metric = self.metrics.get(name)
                    if metric:
                        if labels:
                            metric.labels(**labels).observe(duration)
                        else:
                            metric.observe(duration)
                    else:
                        self.logger.warning("metrics_histogram_not_registered", name=name)
                except Exception as e:
                    self.logger.error("metrics_timing_failed", name=name, error=str(e))
                return result
            return wrapper
        return decorator
