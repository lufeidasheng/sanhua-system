import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Any, Tuple

from core.core2_0.sanhuatongyu.logger import get_logger
from .security.rate_limiter import TokenBucketLimiter
from .security.access_control import AccessControl

_event_bus_instance: Optional["EventBus"] = None
_is_initialized = False
_init_lock = threading.Lock()

class EventBus:
    """
    三花聚顶 · 融合企业级事件总线
    支持：权限检查、全局/事件级/回调级限流、线程池异步分发、事件ID与metrics、兼容脚手架handler、动态订阅与取消
    日志体系：EnterpriseLogger（全局结构化、i18n、多格式）
    """
    def __init__(
        self,
        *,
        global_rate_limit: int = 1000,
        per_event_rate_limit: int = 100,
        access_control: Optional[AccessControl] = None,
        max_workers: int = 20,
        **kwargs,
    ):
        # 订阅者结构: event_type -> [(callback, perms, rate, exception_handler, once_flag)]
        self.subscribers: Dict[str, List[Tuple[Callable, Optional[List[str]], Optional[int], Optional[Callable], bool]]] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="EventBus")
        self.logger = get_logger("eventbus")

        self.access_control = access_control or AccessControl()
        self.global_limiter = TokenBucketLimiter(capacity=global_rate_limit * 2, fill_rate=global_rate_limit)
        self.event_limiters: Dict[str, TokenBucketLimiter] = {}
        self.per_event_rate_limit = per_event_rate_limit

        self._ready = True
        self.metrics = {
            "total_events": 0,
            "event_types": {},
            "errors": 0,
        }

    def is_ready(self) -> bool:
        return self._ready

    def set_ready(self, ready: bool = True):
        self._ready = ready

    def subscribe(
        self,
        event_type: str,
        callback: Callable,
        permissions: Optional[List[str]] = None,
        rate_limit: Optional[int] = None,
        exception_handler: Optional[Callable[[Exception], None]] = None,
        once: bool = False,
    ):
        """
        注册订阅事件。
        :param event_type: 事件类型
        :param callback: 回调函数
        :param permissions: 权限列表
        :param rate_limit: 回调专属限流
        :param exception_handler: 出错时的处理函数
        :param once: 是否仅回调一次
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
            self.event_limiters[event_type] = TokenBucketLimiter(
                capacity=(rate_limit or self.per_event_rate_limit) * 2,
                fill_rate=rate_limit or self.per_event_rate_limit,
            )
        self.subscribers[event_type].append((callback, permissions, rate_limit, exception_handler, once))
        self.logger.info(
            "event_subscribed",
            event=event_type,
            callback=getattr(callback, '__name__', str(callback)),
            once=once
        )

    def unsubscribe(self, event_type: str, callback: Callable):
        """
        取消订阅事件。
        :param event_type: 事件类型
        :param callback: 回调函数
        """
        subs = self.subscribers.get(event_type, [])
        new_subs = [s for s in subs if s[0] != callback]
        self.subscribers[event_type] = new_subs
        self.logger.info("event_unsubscribed", event=event_type, callback=getattr(callback, '__name__', str(callback)))

    def publish(
        self,
        event_type: str,
        event_data: Optional[dict] = None,
        *,
        async_mode: bool = True,
        trace_id: Optional[str] = None,
        requester_role: str = "system",
    ) -> bool:
        """
        发布事件。
        :param event_type: 事件类型
        :param event_data: 事件数据字典
        :param async_mode: 是否异步
        :param trace_id: 追踪ID
        :param requester_role: 请求角色
        :return: 是否发布成功
        """
        if event_data is None:
            event_data = {}

        event_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_data["_event_id"] = event_id
        event_data["_event_time"] = time.time()
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:8]}"
        event_data["trace_id"] = trace_id

        # 全局速率限制
        if not self.global_limiter.consume(1):
            self.logger.warning("global_rate_limit_exceeded", event=event_type)
            return False

        # 事件级速率限制
        limiter = self.event_limiters.get(event_type)
        if limiter and not limiter.consume(1):
            self.logger.warning("event_rate_limit_exceeded", event=event_type)
            return False

        # 权限校验
        if not self.access_control.check_event_permission(requester_role, event_type):
            self.logger.warning(
                "event_publish_permission_denied",
                event=event_type, role=requester_role
            )
            return False

        # 监控
        self.metrics["total_events"] += 1
        self.metrics["event_types"].setdefault(event_type, {"count": 0, "last_processed": None})
        self.metrics["event_types"][event_type]["count"] += 1
        self.metrics["event_types"][event_type]["last_processed"] = time.time()

        # 分发
        callbacks = list(self.subscribers.get(event_type, [])) + list(self.subscribers.get("*", []))
        remove_callbacks = []
        for callback, required_perms, sub_rate, exception_handler, once in callbacks:
            # 权限/速率
            if required_perms and not self._check_permissions(required_perms, callback):
                self.logger.warning(
                    "callback_permission_denied",
                    event=event_type, callback=getattr(callback, '__name__', str(callback))
                )
                continue
            if sub_rate and not self._check_callback_rate_limit(callback, sub_rate):
                self.logger.debug(
                    "callback_rate_limit_skipped",
                    event=event_type, callback=getattr(callback, '__name__', str(callback))
                )
                continue
            # 分发回调
            if async_mode:
                self.executor.submit(
                    self._safe_execute, callback, event_type, event_data.copy(), trace_id, exception_handler
                )
            else:
                self._safe_execute(callback, event_type, event_data, trace_id, exception_handler)
            if once:
                remove_callbacks.append((callback, required_perms, sub_rate, exception_handler, once))
        # 自动移除once
        for cb in remove_callbacks:
            try:
                self.subscribers[event_type].remove(cb)
                self.logger.info("event_once_callback_removed", event=event_type, callback=getattr(cb[0], '__name__', str(cb[0])))
            except Exception:
                pass
        return True

    def _check_callback_rate_limit(self, callback: Callable, rate_limit: int) -> bool:
        if not hasattr(callback, "_rate_limiter"):
            callback._rate_limiter = TokenBucketLimiter(
                capacity=rate_limit * 2, fill_rate=rate_limit
            )
        return callback._rate_limiter.consume(1)

    def _check_permissions(self, required_perms: List[str], callback: Callable) -> bool:
        if hasattr(callback, "__self__") and hasattr(callback.__self__, "meta"):
            module_meta = callback.__self__.meta
            return all(p in module_meta.required_permissions for p in required_perms)
        return True

    def _safe_execute(
        self,
        callback: Callable,
        event_type: str,
        event_data: dict,
        trace_id: str,
        exception_handler: Optional[Callable[[Exception], None]] = None,
    ):
        logger = get_logger("eventbus")
        with logger.with_trace_id(trace_id):
            try:
                start = time.time()
                # 兼容旧 handler
                if self._is_payload_handler(callback):
                    callback(event_data)
                else:
                    callback(event_type, event_data)
                duration = time.time() - start
                event_data["processing_time"] = duration
                logger.debug(
                    "event_processed",
                    event=event_type, time=f"{duration:.4f}s"
                )
            except Exception as e:
                self.metrics["errors"] += 1
                logger.error(
                    "event_failed",
                    event=event_type, error=str(e),
                    exc=e
                )
                if exception_handler:
                    try:
                        exception_handler(e)
                    except Exception as ex:
                        logger.error(
                            "exception_handler_failed",
                            error=str(ex),
                            exc=ex
                        )

    def _is_payload_handler(self, callback: Callable) -> bool:
        try:
            import inspect
            params = inspect.signature(callback).parameters
            return len(params) == 1
        except Exception:
            return False

    def update_rate_limits(
        self,
        *,
        global_limit: Optional[int] = None,
        per_event_limit: Optional[int] = None,
    ):
        if global_limit is not None:
            self.global_limiter.update_rate(global_limit)
            self.logger.info("global_rate_limit_updated", new_limit=global_limit)
        if per_event_limit is not None:
            self.per_event_rate_limit = per_event_limit
            for limiter in self.event_limiters.values():
                limiter.update_rate(per_event_limit)
            self.logger.info("per_event_rate_limit_updated", new_limit=per_event_limit)

    def set_access_control(self, ac: AccessControl):
        self.access_control = ac
        self.logger.info("access_control_set")

    def shutdown(self):
        self._ready = False
        self.executor.shutdown(wait=False)
        self.subscribers.clear()
        self.logger.info("eventbus_shutdown")

    def get_metrics(self) -> Dict[str, Any]:
        return dict(self.metrics)

# ==== 全局单例API ====
def init_event_bus(config: Dict[str, Any]) -> EventBus:
    global _event_bus_instance, _is_initialized
    with _init_lock:
        if not _is_initialized:
            _event_bus_instance = EventBus(
                global_rate_limit=config.get("global_rate_limit", 1000),
                per_event_rate_limit=config.get("per_event_rate_limit", 100),
                max_workers=config.get("thread_pool_size", 20),
            )
            _is_initialized = True
    return _event_bus_instance

def get_event_bus() -> EventBus:
    if not _is_initialized or _event_bus_instance is None:
        raise RuntimeError("事件总线未初始化，请先调用 init_event_bus()")
    return _event_bus_instance

def is_event_bus_initialized() -> bool:
    return _is_initialized

__all__ = [
    "EventBus",
    "init_event_bus",
    "get_event_bus",
    "is_event_bus_initialized",
]
