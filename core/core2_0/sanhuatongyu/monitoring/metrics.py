"""
core.core2_0/sanhuatongyu/monitoring/metrics.py
三花聚顶 · 监控指标模块 (Fedora 兼容/纯Python自适应版 · hardened)

特性：
- 有 prometheus_client：暴露 /metrics（start_http_server）
- 无 prometheus_client：降级为内存指标（可被 sysmon/health_check 拉取）
- 兼容结构化 logger 与标准 logging（避免 logger.info(event, **kwargs) 在降级时炸）
- 并发安全：metrics 字典访问加锁
- time_function：无论成功/失败都记录耗时（finally）
- Prometheus server 启动幂等，避免重复 start
"""

from __future__ import annotations

import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable

# 尝试导入 prometheus_client，如果失败则降级
try:
    from prometheus_client import start_http_server, Counter, Gauge, Histogram  # type: ignore
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False
    start_http_server = None  # type: ignore
    Counter = Gauge = Histogram = None  # type: ignore


# ================== logger 兼容层 ==================

def _get_logger():
    try:
        from core.core2_0.sanhuatongyu.logger import get_logger  # type: ignore
        return get_logger("metrics")
    except Exception:
        return logging.getLogger("metrics")


logger = _get_logger()


class _SafeLogger:
    """
    统一 logger 调用方式：
    - 如果是结构化 logger（支持 logger.info("event", k=v...)），直接传
    - 如果是标准 logging.Logger，则把 fields 格式化到 message 里
    """
    def __init__(self, base):
        self._base = base or logging.getLogger("metrics")

    def _supports_kwargs(self) -> bool:
        # 粗暴但实用：你企业 logger 一般接受 kwargs；标准 logging 不接受
        # 即使误判，下面也有 try/except 容错
        return not isinstance(self._base, logging.Logger)

    def _fmt(self, event: str, fields: Dict[str, Any]) -> str:
        if not fields:
            return str(event)
        tail = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields.keys()))
        return f"{event} | {tail}"

    def info(self, event: str, **fields):
        try:
            if self._supports_kwargs():
                self._base.info(event, **fields)
            else:
                self._base.info(self._fmt(event, fields))
        except Exception:
            self._base.info(self._fmt(event, fields))

    def debug(self, event: str, **fields):
        try:
            if self._supports_kwargs():
                self._base.debug(event, **fields)
            else:
                self._base.debug(self._fmt(event, fields))
        except Exception:
            self._base.debug(self._fmt(event, fields))

    def warning(self, event: str, **fields):
        try:
            if self._supports_kwargs():
                self._base.warning(event, **fields)
            else:
                self._base.warning(self._fmt(event, fields))
        except Exception:
            self._base.warning(self._fmt(event, fields))

    def error(self, event: str, **fields):
        try:
            if self._supports_kwargs():
                self._base.error(event, **fields)
            else:
                self._base.error(self._fmt(event, fields))
        except Exception:
            self._base.error(self._fmt(event, fields))


log = _SafeLogger(logger)


# ================== 单例控制 ==================

_metrics_singleton: Optional["PrometheusExporter"] = None
_metrics_lock = threading.Lock()


def get_metrics_exporter(port: int = 8000) -> "PrometheusExporter":
    """获取/创建全局唯一 metrics exporter"""
    global _metrics_singleton
    with _metrics_lock:
        if _metrics_singleton is None:
            _metrics_singleton = PrometheusExporter(port)
        return _metrics_singleton


# ================== 降级模式数据结构 ==================

@dataclass
class _SimpleCounter:
    value: float = 0.0


@dataclass
class _SimpleGauge:
    value: float = 0.0


@dataclass
class _SimpleHistogram:
    # 简化但更有用：记录 count/sum/min/max + 最近 N 条样本
    count: int = 0
    total: float = 0.0
    min_v: Optional[float] = None
    max_v: Optional[float] = None
    samples: List[float] = None  # type: ignore
    max_samples: int = 200

    def __post_init__(self):
        if self.samples is None:
            self.samples = []

    def observe(self, v: float):
        self.count += 1
        self.total += float(v)
        self.min_v = float(v) if self.min_v is None else min(self.min_v, float(v))
        self.max_v = float(v) if self.max_v is None else max(self.max_v, float(v))
        self.samples.append(float(v))
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]


# ================== Exporter ==================

class PrometheusExporter:
    """
    Prometheus 监控导出器 (兼容 Fedora/纯Python环境)
    - 有 prometheus_client：使用真实 Counter/Gauge/Histogram
    - 无 prometheus_client：使用内存简化实现
    """
    def __init__(self, port: int = 8000):
        self.port = int(port or 0)
        self.metrics: Dict[str, Any] = {}
        self.prometheus_mode = bool(PROMETHEUS_AVAILABLE)
        self._m_lock = threading.RLock()
        self._server_started = False

        # 允许通过环境变量禁用（比如某些 GUI/子进程不想开端口）
        if os.environ.get("SANHUA_METRICS_DISABLE", "").strip().lower() in ("1", "true", "yes", "on"):
            self.prometheus_mode = False

        if self.prometheus_mode and self.port > 0:
            self._start_server_once()
        elif PROMETHEUS_AVAILABLE and self.port <= 0:
            # 用户传 0 表示“不开端口但仍可用 prometheus 类型对象”（很少用，但支持）
            log.info("prometheus_server_skipped", port=self.port, reason="port<=0")
        else:
            log.warning("prometheus_client_not_installed", action="using_simplified_metrics")

    def _start_server_once(self) -> None:
        with self._m_lock:
            if self._server_started:
                return
            try:
                # start_http_server 是幂等风险点：重复启动同端口会抛异常
                start_http_server(self.port)  # type: ignore
                self._server_started = True
                log.info("prometheus_server_started", port=self.port)
            except Exception as e:
                self.prometheus_mode = False
                self._server_started = False
                log.error("prometheus_server_failed", port=self.port, error=str(e))

    # ---------- register ----------

    def register_counter(self, name: str, description: str, labels: Optional[List[str]] = None) -> None:
        with self._m_lock:
            if name in self.metrics:
                log.warning("metric_already_registered", name=name, type="counter")
                return
            if self.prometheus_mode:
                self.metrics[name] = Counter(name, description, labels or [])  # type: ignore
            else:
                self.metrics[name] = _SimpleCounter()
            log.debug("counter_registered", name=name, labels=labels or [])

    def register_gauge(self, name: str, description: str, labels: Optional[List[str]] = None) -> None:
        with self._m_lock:
            if name in self.metrics:
                log.warning("metric_already_registered", name=name, type="gauge")
                return
            if self.prometheus_mode:
                self.metrics[name] = Gauge(name, description, labels or [])  # type: ignore
            else:
                self.metrics[name] = _SimpleGauge()
            log.debug("gauge_registered", name=name, labels=labels or [])

    def register_histogram(
        self,
        name: str,
        description: str,
        buckets: Optional[List[float]] = None,
        labels: Optional[List[str]] = None,
        *,
        max_samples: int = 200,
    ) -> None:
        with self._m_lock:
            if name in self.metrics:
                log.warning("metric_already_registered", name=name, type="histogram")
                return
            if self.prometheus_mode:
                b = buckets if buckets else (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
                self.metrics[name] = Histogram(name, description, labels or [], buckets=b)  # type: ignore
            else:
                h = _SimpleHistogram(max_samples=max_samples)
                self.metrics[name] = h
            log.debug("histogram_registered", name=name, labels=labels or [])

    # ---------- update ----------

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        with self._m_lock:
            m = self.metrics.get(name)
        if not m:
            log.error("metric_not_registered", name=name, op="increment")
            return

        if self.prometheus_mode:
            try:
                if labels:
                    m.labels(**labels).inc(value)  # type: ignore
                else:
                    m.inc(value)  # type: ignore
            except Exception as e:
                log.error("increment_failed", name=name, error=str(e))
        else:
            if isinstance(m, _SimpleCounter):
                m.value += float(value)
                log.debug("simplified_increment", name=name, value=m.value)

    def set_value(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        with self._m_lock:
            m = self.metrics.get(name)
        if not m:
            log.error("metric_not_registered", name=name, op="set_value")
            return

        if self.prometheus_mode:
            try:
                if labels:
                    m.labels(**labels).set(value)  # type: ignore
                else:
                    m.set(value)  # type: ignore
            except Exception as e:
                log.error("set_value_failed", name=name, error=str(e))
        else:
            if isinstance(m, _SimpleGauge):
                m.value = float(value)
                log.debug("simplified_set_value", name=name, value=m.value)

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        with self._m_lock:
            m = self.metrics.get(name)
        if not m:
            log.error("metric_not_registered", name=name, op="observe")
            return

        if self.prometheus_mode:
            try:
                if labels:
                    m.labels(**labels).observe(value)  # type: ignore
                else:
                    m.observe(value)  # type: ignore
            except Exception as e:
                log.error("observe_failed", name=name, error=str(e))
        else:
            if isinstance(m, _SimpleHistogram):
                m.observe(float(value))
                log.debug("simplified_observe", name=name, value=float(value))

    # ---------- timing ----------

    def time_function(self, name: str, labels: Optional[Dict[str, str]] = None) -> Callable:
        """函数执行时间测量装饰器（支持同步/异步函数；异常也记录耗时）"""
        def decorator(func):
            import functools
            import inspect

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start_time
                    self._record_timing(name, duration, labels)

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    duration = time.perf_counter() - start_time
                    self._record_timing(name, duration, labels)

            return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

        return decorator

    def _record_timing(self, name: str, duration: float, labels: Optional[Dict[str, str]] = None) -> None:
        # timing 约定：优先写 histogram
        with self._m_lock:
            m = self.metrics.get(name)

        if not m:
            log.warning("histogram_not_registered", name=name)
            return

        if self.prometheus_mode:
            try:
                # Histogram/ Summary 都有 observe；这里不强依赖 class 名
                if labels:
                    m.labels(**labels).observe(duration)  # type: ignore
                else:
                    m.observe(duration)  # type: ignore
            except Exception as e:
                log.error("timing_failed", name=name, error=str(e))
        else:
            if isinstance(m, _SimpleHistogram):
                m.observe(float(duration))
                log.debug("simplified_timing", name=name, value=float(duration))

    # ---------- read ----------

    def get_metric_value(self, name: str) -> Any:
        """通用获取指标当前值（降级用）。Prometheus 模式不直接提供值。"""
        with self._m_lock:
            m = self.metrics.get(name)

        if not m:
            return None

        if self.prometheus_mode:
            return None

        if isinstance(m, _SimpleCounter):
            return m.value
        if isinstance(m, _SimpleGauge):
            return m.value
        if isinstance(m, _SimpleHistogram):
            avg = (m.total / m.count) if m.count else 0.0
            return {
                "count": m.count,
                "sum": m.total,
                "avg": avg,
                "min": m.min_v,
                "max": m.max_v,
                "samples": list(m.samples),
            }
        return None

    def list_metrics(self) -> List[str]:
        with self._m_lock:
            return list(self.metrics.keys())