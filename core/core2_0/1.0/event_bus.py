import os
import ssl
import time
import uuid
import logging
import threading
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, List
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

# 可选依赖 cryptography，实现精准证书校验
CRYPTOGRAPHY_AVAILABLE = False
try:
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger("event_bus")


class EventBus:
    """
    三花聚顶企业级事件总线模块
    
    功能：
    - 事件同步/异步发布
    - 事件订阅管理
    - 异常安全捕获，防止中断
    - 访问控制及限流接口预留
    - 证书安全校验
    - 性能及错误统计
    """
    def __init__(self, config: Dict[str, Any]):
        # 校验配置
        required_keys = {'thread_pool_size'}
        if not required_keys.issubset(config):
            missing = required_keys - config.keys()
            raise ValueError(f"缺少必要配置项: {missing}")

        self.config = config
        self.logger = logger

        self._executor = ThreadPoolExecutor(
            max_workers=config.get("thread_pool_size", 10),
            thread_name_prefix="EventBusWorker"
        )
        self.reply_dispatcher = None
        self._shutdown_flag = False
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._subscription_lock = threading.RLock()
        self._metrics_lock = threading.Lock()
        self._event_metrics: Dict[str, Any] = {
            "total_events": 0,
            "event_types": {},
            "errors": 0
        }
        self._ready = True

        # 访问控制和限流接口预留
        self._access_control = None
        self._global_rate_limit = config.get("global_rate_limit")
        self._per_event_rate_limit = config.get("per_event_rate_limit")

    def is_ready(self) -> bool:
        """事件总线准备状态"""
        return self._ready and not self._shutdown_flag

    def set_reply_dispatcher(self, dispatcher: Any) -> None:
        with self._subscription_lock:
            self.reply_dispatcher = dispatcher
            self.logger.info("回复分发器已绑定到事件总线")

    def publish(self, event_type: str, payload: Dict[str, Any], exception_handler: Optional[Callable[[Exception], None]] = None) -> None:
        if self._shutdown_flag:
            self.logger.warning(f"事件总线关闭中，忽略事件: {event_type}")
            return

        if self._global_rate_limit is not None:
            # TODO: 这里可以实现真实限流机制
            self.logger.debug(f"全局限流阈值: {self._global_rate_limit}")

        start = time.monotonic()
        event_id = str(uuid.uuid4())
        enriched_payload = {
            **payload,
            "_metadata_event_bus": {
                "event_id": event_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type
            }
        }

        self._update_metrics(event_type, "published")

        with self._subscription_lock:
            handlers = self._subscriptions.get(event_type, []) + self._subscriptions.get("*", [])

        for handler in handlers:
            try:
                handler(enriched_payload)
                self._update_metrics(event_type, "processed")
            except Exception as e:
                self._update_metrics(event_type, "failed")
                self.logger.error(f"事件处理失败: {event_type} -> {getattr(handler, '__name__', repr(handler))}, 错误: {e}", exc_info=True)
                if exception_handler:
                    try:
                        exception_handler(e)
                    except Exception as eh:
                        self.logger.error(f"异常回调执行失败: {eh}", exc_info=True)

        elapsed = time.monotonic() - start
        if elapsed > 0.5:
            self.logger.warning(f"事件处理耗时过长: {event_type} 耗时 {elapsed:.3f}s")

    def emit(self, event_type: str, payload: Optional[Dict[str, Any]] = None, exception_handler: Optional[Callable[[Exception], None]] = None) -> None:
        if payload is None:
            payload = {}
        self.publish(event_type, payload, exception_handler=exception_handler)

    async def publish_async(self, event_type: str, payload: Dict[str, Any], exception_handler: Optional[Callable[[Exception], None]] = None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.logger.warning("异步发布时无事件循环，降级为同步发布")
            self.publish(event_type, payload, exception_handler=exception_handler)
            return

        await loop.run_in_executor(self._executor, self.publish, event_type, payload, exception_handler)

    async def emit_async(self, event_type: str, payload: Optional[Dict[str, Any]] = None, exception_handler: Optional[Callable[[Exception], None]] = None) -> None:
        if payload is None:
            payload = {}
        await self.publish_async(event_type, payload, exception_handler=exception_handler)

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        if not callable(handler):
            raise ValueError("事件处理器必须是可调用对象")

        with self._subscription_lock:
            self._subscriptions.setdefault(event_type, []).append(handler)

        self.logger.info(f"订阅事件: {event_type} -> {getattr(handler, '__name__', repr(handler))}")

    def unsubscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        with self._subscription_lock:
            handlers = self._subscriptions.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
                self.logger.info(f"取消订阅事件: {event_type} -> {getattr(handler, '__name__', repr(handler))}")

    def clear_subscriptions(self, event_type: Optional[str] = None) -> None:
        with self._subscription_lock:
            if event_type:
                self._subscriptions.pop(event_type, None)
                self.logger.info(f"清理事件订阅: {event_type}")
            else:
                self._subscriptions.clear()
                self.logger.info("清理所有事件订阅")

    @lru_cache(maxsize=1)
    def _validate_certificate(self, cert_path: str) -> bool:
        if not CRYPTOGRAPHY_AVAILABLE:
            return self._validate_certificate_with_stdlib(cert_path)
        try:
            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read(), default_backend())
            now = datetime.now(timezone.utc)
            valid_from = cert.not_valid_before.replace(tzinfo=timezone.utc)
            valid_to = cert.not_valid_after.replace(tzinfo=timezone.utc)
            if now < valid_from:
                self.logger.error(f"证书尚未生效 (生效时间: {valid_from})")
                return False
            if now > valid_to:
                self.logger.error(f"证书已过期 (过期时间: {valid_to})")
                return False
            return True
        except Exception as e:
            self.logger.exception(f"证书校验异常: {e}")
            return False

    def _validate_certificate_with_stdlib(self, cert_path: str) -> bool:
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cafile=cert_path)
            return True
        except Exception as e:
            self.logger.exception(f"标准库证书校验失败: {e}")
            return False

    def _update_metrics(self, event_type: str, action: str) -> None:
        with self._metrics_lock:
            self._event_metrics["total_events"] += 1
            if action == "failed":
                self._event_metrics["errors"] += 1
            if event_type not in self._event_metrics["event_types"]:
                self._event_metrics["event_types"][event_type] = {"count": 0, "last_processed": None}
            if action in ("processed", "published"):
                self._event_metrics["event_types"][event_type]["count"] += 1
                self._event_metrics["event_types"][event_type]["last_processed"] = time.time()

    def get_metrics(self) -> Dict[str, Any]:
        with self._metrics_lock:
            queue_size = -1
            active_threads = -1
            try:
                queue_size = self._executor._work_queue.qsize()
            except Exception:
                pass
            try:
                if hasattr(self._executor, "_max_workers") and hasattr(self._executor, "_idle_semaphore"):
                    active_threads = self._executor._max_workers - self._executor._idle_semaphore._value
            except Exception:
                pass
            return {
                **self._event_metrics,
                "subscription_counts": {et: len(h) for et, h in self._subscriptions.items()},
                "queue_size": queue_size,
                "active_threads": active_threads,
            }

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        self.logger.info(f"事件总线关闭中，超时设置: {timeout}s")
        self._shutdown_flag = True
        self._executor.shutdown(wait=False)
        if wait:
            start = time.monotonic()
            while not self._executor._work_queue.empty():
                if time.monotonic() - start > timeout:
                    self.logger.warning("事件总线关闭超时，强制退出")
                    break
                time.sleep(0.5)
        self.clear_subscriptions()
        self.logger.info("事件总线已成功关闭")


# 全局事件总线单例与状态
_event_bus_instance: Optional[EventBus] = None
_is_initialized = False
_init_lock = threading.Lock()


def init_event_bus(config: Dict[str, Any]) -> EventBus:
    global _event_bus_instance, _is_initialized
    with _init_lock:
        if not _is_initialized:
            _event_bus_instance = EventBus(config)
            _is_initialized = True
            cert_path = config.get("cert_path")
            if cert_path and not _event_bus_instance._validate_certificate(cert_path):
                logger.error("证书校验失败，存在安全隐患")
    return _event_bus_instance


def get_event_bus() -> EventBus:
    if not _is_initialized:
        raise RuntimeError("事件总线未初始化，请先调用 init_event_bus()")
    return _event_bus_instance


def is_event_bus_initialized() -> bool:
    return _is_initialized


def emit(event_type: str, payload: Dict[str, Any]) -> None:
    try:
        get_event_bus().publish(event_type, payload)
    except Exception as e:
        logger.error(f"事件发布失败: {e}", exc_info=True)


async def emit_async(event_type: str, payload: Dict[str, Any]) -> None:
    try:
        await get_event_bus().publish_async(event_type, payload)
    except Exception as e:
        logger.error(f"异步事件发布失败: {e}", exc_info=True)


__all__ = [
    "EventBus",
    "init_event_bus",
    "get_event_bus",
    "is_event_bus_initialized",
    "emit",
    "emit_async",
]
