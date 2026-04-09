"""
三花聚顶 · reply_dispatcher 智能回复分发器（企业标准增强版）
作者: 三花聚顶开发团队
版本: 2.1.2
"""
import time
import uuid
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from typing import Dict, Any, Optional

from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.events import get_event_bus, is_event_bus_initialized
from core.core2_0.sanhuatongyu.module.base import BaseModule

logger = get_logger("reply_dispatcher")


class ModuleState(Enum):
    INITIALIZING = auto()
    READY = auto()
    PROCESSING = auto()
    DEGRADED = auto()
    ERROR = auto()
    SHUTTING_DOWN = auto()
    TERMINATED = auto()

    @classmethod
    def is_active(cls, state):
        return state in [cls.READY, cls.PROCESSING, cls.DEGRADED]


class ReplyDispatcherModule(BaseModule):
    """三花聚顶 · 智能回复分发器 (企业标准)"""
    VERSION = "2.1.2"

    def __init__(self, meta, context):
        super().__init__(meta, context)
        self.state = ModuleState.INITIALIZING
        self.config = self._init_config()
        self.thread_pool = self._init_thread_pool()
        self._pending_tasks: Dict[str, Any] = {}
        self._task_queue = queue.Queue(maxsize=self.config['max_queue_size'])
        self.lock = threading.RLock()
        self.metrics = self._init_metrics()
        self._event_handlers = {}
        self._monitor_thread = threading.Thread(
            target=self._monitor_operations,
            daemon=True,
            name="ReplyDispatcher-Monitor"
        )
        self._registered = False

    def _init_config(self) -> dict:
        default_config = {
            "max_workers": 8,
            "reply_timeout": 15,
            "max_queue_size": 100,
            "rate_limit": 60,
            "degraded_threshold": 0.8
        }
        custom = self.context.config_manager.get("reply_dispatcher", {}) if hasattr(self.context, "config_manager") else {}
        return {**default_config, **custom}

    def _init_thread_pool(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(
            max_workers=self.config['max_workers'],
            thread_name_prefix="ReplyDispatcher-"
        )

    def _init_metrics(self) -> dict:
        return {
            "total_replies": 0,
            "errors": 0,
            "timeouts": 0,
            "pending": 0,
            "queue_size": 0,
            "start_time": time.time(),
            "last_active": time.time()
        }

    # === 标准生命周期 ===
    def preload(self):
        logger.info(f"{self.meta.name} v{self.VERSION} 预加载完成")

    def setup(self):
        logger.info("设置 reply_dispatcher")
        # 必须用 func=，禁止第二个参数！
        if hasattr(self.context, "register_action") and not self._registered:
            self.context.register_action("reply", func=self.reply)
            self.context.register_action("get_status", func=self.get_status)
            self.context.register_action("emergency_stop", func=self.emergency_stop)
            self._registered = True

    def start(self):
        logger.info("启动 reply_dispatcher")
        if is_event_bus_initialized():
            eb = get_event_bus()
            self._event_handlers["USER_QUERY"] = eb.subscribe("USER_QUERY", self.handle_user_query)
            self._event_handlers["SYSTEM_HEALTH_CHECK"] = eb.subscribe("SYSTEM_HEALTH_CHECK", self.handle_health_check)
        if not self._monitor_thread.is_alive():
            self._monitor_thread.start()
        self.state = ModuleState.READY
        logger.info("reply_dispatcher 已就绪")

    def stop(self):
        logger.info("停止 reply_dispatcher")
        self.state = ModuleState.SHUTTING_DOWN
        self.thread_pool.shutdown(wait=True)
        self._cleanup_event_subscriptions()

    def on_shutdown(self):
        logger.info("关闭 reply_dispatcher")
        self.state = ModuleState.TERMINATED
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

    def emergency_stop(self, **kwargs):
        logger.critical("执行紧急停止!")
        self.state = ModuleState.SHUTTING_DOWN
        self.thread_pool.shutdown(wait=False)
        self._cleanup_event_subscriptions()
        return {"status": "emergency_stopped"}

    def _cleanup_event_subscriptions(self):
        if is_event_bus_initialized():
            eb = get_event_bus()
            for event, handler in self._event_handlers.items():
                eb.unsubscribe(event, handler)
            self._event_handlers.clear()

    def handle_event(self, event_type: str, event_data: dict) -> Optional[dict]:
        if event_type == "MODULE_STATUS_REQUEST":
            return self.get_status()
        return None

    def reply(self, query: str, user: Optional[str] = None, **kwargs) -> str:
        if not query or len(query.strip()) == 0:
            raise ValueError("空查询请求")
        if self.state != ModuleState.READY:
            return self._get_degraded_response()
        reply_id = f"reply-{uuid.uuid4().hex[:8]}"
        logger.info("收到回复请求", extra={
            "query": query[:100],
            "user": user,
            "reply_id": reply_id
        })
        try:
            response = self._generate_response(query, user)
            if is_event_bus_initialized():
                get_event_bus().publish("QUERY_RESULT", {
                    "reply_id": reply_id,
                    "response": response,
                    "user": user,
                    "query": query,
                    "timestamp": time.time()
                })
            self.metrics["total_replies"] += 1
            self.metrics["last_active"] = time.time()
            return response
        except Exception as e:
            self.metrics["errors"] += 1
            logger.error("回复处理失败", extra={
                "error": str(e),
                "query": query[:100],
                "user": user
            })
            return self._get_error_response()

    def _generate_response(self, query: str, user: Optional[str]) -> str:
        user_txt = user if user else ""
        return f"🌸[AI]: 您好{user_txt}，您的问题是：{query[:50]}..."

    def _get_degraded_response(self) -> str:
        return "⚠️ 系统繁忙，请稍后再试"

    def _get_error_response(self) -> str:
        return "❌ 回复处理失败，请重试"

    def get_status(self, detailed: bool = False, **kwargs) -> dict:
        status = {
            "module": self.meta.name,
            "version": self.VERSION,
            "state": self.state.name,
            "uptime": int(time.time() - self.metrics["start_time"]),
            "metrics": {
                "total_replies": self.metrics["total_replies"],
                "errors": self.metrics["errors"],
                "timeouts": self.metrics["timeouts"],
                "pending": self.metrics["pending"],
                "queue_size": self._task_queue.qsize(),
                "threads": self.thread_pool._work_queue.qsize() if hasattr(self.thread_pool, "_work_queue") else None
            }
        }
        if detailed:
            status["config"] = self.config
            status["thread_pool"] = {
                "max_workers": self.thread_pool._max_workers,
                "active_threads": threading.active_count()
            }
        logger.debug("状态查询", extra=status)
        return status

    def _monitor_operations(self):
        while self.state != ModuleState.TERMINATED:
            try:
                self._check_timeouts()
                self._adjust_throughput()
                time.sleep(5)
            except Exception as e:
                logger.error(f"监控线程异常: {str(e)}")
                time.sleep(10)

    def _check_timeouts(self):
        with self.lock:
            current_time = time.time()
            timed_out = [
                task_id for task_id, (_, start_time) in self._pending_tasks.items()
                if current_time - start_time > self.config['reply_timeout']
            ]
            for task_id in timed_out:
                self._pending_tasks.pop(task_id, None)
                self.metrics["timeouts"] += 1
                self.metrics["pending"] -= 1
                logger.warning(f"任务超时: {task_id}")

    def _adjust_throughput(self):
        queue_ratio = self.metrics['queue_size'] / self.config['max_queue_size']
        if queue_ratio > self.config['degraded_threshold'] and self.state == ModuleState.READY:
            self.state = ModuleState.DEGRADED
            logger.warning("进入降级模式")
            if is_event_bus_initialized():
                get_event_bus().publish(
                    "REPLY_DISPATCHER_DEGRADED",
                    {"reason": "high_queue_load", "queue_ratio": queue_ratio}
                )

    def handle_user_query(self, event_data: dict):
        if self.state != ModuleState.READY:
            logger.warning("拒绝处理查询: 模块未就绪")
            return
        try:
            query = event_data.get("text", "")
            user = event_data.get("user", "anonymous")
            if self._task_queue.full():
                logger.warning("任务队列已满，拒绝新查询")
                return
            future = self.thread_pool.submit(self._process_async_query, query, user)
            task_id = str(uuid.uuid4())
            with self.lock:
                self._pending_tasks[task_id] = (future, time.time())
                self.metrics["pending"] += 1
                self.metrics["queue_size"] = self._task_queue.qsize()
            future.add_done_callback(
                lambda f: self._handle_async_result(f, task_id)
            )
        except Exception as e:
            logger.error("处理用户查询失败", extra={"error": str(e)})

    def _process_async_query(self, query: str, user: str) -> str:
        return self.reply(query, user)

    def _handle_async_result(self, future, task_id: str):
        with self.lock:
            self._pending_tasks.pop(task_id, None)
            self.metrics["pending"] -= 1
            self.metrics["queue_size"] = self._task_queue.qsize()
        try:
            result = future.result()
            logger.info("异步回复完成", extra={"result": result[:100]})
        except Exception as e:
            logger.error("异步回复失败", extra={"error": str(e)})

    def handle_health_check(self, event_data: dict):
        status = self.get_status()
        if is_event_bus_initialized():
            get_event_bus().publish("HEALTH_STATUS", status)

    def health_check(self) -> dict:
        return {
            "status": self.state.name,
            "module": self.meta.name,
            "version": self.VERSION,
            "metrics": self.metrics,
            "timestamp": time.time()
        }

    @classmethod
    def register_actions(cls, dispatcher, context=None):
        instance = cls(meta=dispatcher.get_module_meta("reply_dispatcher"), context=context)
        dispatcher.register_action("reply", func=instance.reply)
        dispatcher.register_action("get_status", func=instance.get_status)
        dispatcher.register_action("emergency_stop", func=instance.emergency_stop)
        logger.info("reply_dispatcher 动作已注册")

def register_actions(dispatcher, context=None):
    ReplyDispatcherModule.register_actions(dispatcher, context)

MODULE_CLASS = ReplyDispatcherModule
