import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict

import config
from core.core2_0.event_bus import get_event_bus, is_event_bus_initialized

logger = logging.getLogger("ReplyDispatcher")

# 获取事件总线实例（如果已初始化）
if is_event_bus_initialized():
    event_bus = get_event_bus()
else:
    event_bus = None
    # 这里可以做事件总线未初始化时的降级处理，比如日志告警

class ProcessingState(Enum):
    """请求处理状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CIRCUIT_BROKEN = "circuit_broken"
    REJECTED = "rejected"

class CircuitBrokenError(Exception):
    """断路器异常"""
    pass

class ReplyDispatcher:
    def __init__(
        self,
        ai_core=None,
        command_router=None,
        max_workers: int = config.REPLY_THREAD_POOL_SIZE,
        reply_timeout: int = config.REPLY_PROCESSING_TIMEOUT
    ):
        logger.info("ReplyDispatcher 初始化开始")
        self.ai_core = ai_core  # AI核心接口，负责具体聊天推理
        self.command_router = command_router  # 命令路由器，判断是否为命令并执行
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ReplyWorker-")
        self.reply_timeout = reply_timeout  # 请求处理超时阈值（秒）
        
        self.circuit_breaker = self._create_circuit_breaker()  # 简单断路器实例
        self.health_monitor = self._create_health_monitor()    # 简单健康监控
        
        self.active_requests: Dict[str, Dict] = {}  # 记录当前活跃请求状态
        self.request_lock = threading.RLock()       # 线程安全锁
        
        # 延迟订阅事件列表（事件类型，处理函数）
        self._delayed_subscriptions = [
            ("USER_QUERY", self.handle_query_event),
            ("SYSTEM_HEALTH_CHECK", self.handle_health_check),
        ]
        
        self._subscribe_to_events()  # 订阅事件
        
        # 请求监控线程
        self._monitor_thread = threading.Thread(target=self._monitor_requests, daemon=True, name="ReplyDispatcher-Monitor")
        self._monitor_thread.start()
        
        # 定时健康报告线程
        self._health_report_thread = threading.Thread(target=self._periodic_health_report, daemon=True, name="Health-Reporter")
        self._health_report_thread.start()
        
        logger.info("ReplyDispatcher 初始化完成")

    def _create_circuit_breaker(self):
        """创建简易断路器"""
        class SimpleCircuitBreaker:
            def __init__(self):
                self._state = "closed"
                self.failure_count = 0
                self.success_count = 0
                self.last_failure_time = 0
                
            @property
            def is_open(self):
                return self._state == "open"
                
            @property
            def state(self):
                return self._state
                
            def record_success(self):
                if self._state == "half-open":
                    self.success_count += 1
                    if self.success_count >= 3:
                        self._state = "closed"
                        self.failure_count = 0
                        self.success_count = 0
                else:
                    self.success_count += 1
                    
            def record_failure(self):
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= 5:
                    self._state = "open"
                    
            def allow_request(self):
                if self._state == "open":
                    if time.time() - self.last_failure_time > 30:
                        self._state = "half-open"
                        return True
                    return False
                return True
                
        return SimpleCircuitBreaker()

    def _create_health_monitor(self):
        """创建简易健康监控"""
        class SimpleHealthMonitor:
            def __init__(self):
                self.active_requests = 0
                self.failure_count = 0
                self.success_count = 0
                self.rejection_count = 0
                self.max_queue_size = getattr(config, "MAX_QUEUE_SIZE", 100)
                
            @property
            def is_overloaded(self):
                return self.active_requests > self.max_queue_size * 0.8
                
            @property
            def queue_utilization(self):
                return self.active_requests / self.max_queue_size if self.max_queue_size else 0
                
            def record_request_submitted(self):
                self.active_requests += 1
                
            def record_success(self):
                self.success_count += 1
                self.active_requests -= 1
                
            def record_failure(self):
                self.failure_count += 1
                self.active_requests -= 1
                
            def record_rejection(self):
                self.rejection_count += 1
                
            @property
            def current_failure_rate(self):
                total = self.success_count + self.failure_count
                return self.failure_count / total if total > 0 else 0.0
                
        return SimpleHealthMonitor()

    def _subscribe_to_events(self):
        """订阅事件总线事件"""
        logger.info("执行延迟事件订阅")
        if event_bus is None:
            logger.warning("事件总线未初始化，无法订阅事件")
            return
        for event_type, handler in self._delayed_subscriptions:
            if callable(handler):
                event_bus.subscribe(event_type, handler)
                logger.info(f"订阅事件 {event_type} -> {handler.__name__}")
            else:
                logger.error(f"事件处理函数不可调用: {handler}")

    def handle_query_event(self, payload: Dict[str, Any]):
        """处理查询事件，调度任务"""
        logger.info(f"收到查询事件: {payload.get('text', '')[:50]}")
        
        # 断路器保护
        if self.circuit_breaker.is_open:
            logger.warning("断路器打开，拒绝请求")
            self._reject_request(payload, reason="circuit_broken")
            return
        
        # 健康监测拒绝过载请求
        if self.health_monitor.is_overloaded:
            logger.warning("系统过载，拒绝请求")
            self._reject_request(payload, reason="overloaded")
            return
        
        request_id = str(uuid.uuid4())
        
        with self.request_lock:
            self.active_requests[request_id] = {
                "payload": payload,
                "state": ProcessingState.PENDING,
                "start_time": time.time(),
                "future": None,
                "result": None,
                "error": None,
            }
        
        try:
            # 异步线程池提交查询任务
            future = self.executor.submit(self._process_query, request_id, payload)
            future.add_done_callback(lambda fut: self._handle_processing_result(request_id, fut))
            
            with self.request_lock:
                self.active_requests[request_id]["state"] = ProcessingState.PROCESSING
                self.active_requests[request_id]["future"] = future
            
            self.health_monitor.record_request_submitted()
            logger.debug(f"请求 {request_id} 已提交处理")
            
        except Exception as e:
            logger.error(f"请求提交失败: {request_id}, 错误: {str(e)}")
            with self.request_lock:
                if request_id in self.active_requests:
                    self.active_requests[request_id]["state"] = ProcessingState.FAILED
                    self.active_requests[request_id]["error"] = str(e)
            self.health_monitor.record_failure()
    
    def _process_query(self, request_id: str, payload: Dict[str, Any]) -> Any:
        """具体查询处理逻辑"""
        text = payload.get("text", "")
        logger.debug(f"处理请求 {request_id}，内容：{text[:50]}")
        try:
            # 命令路由优先
            if self.command_router:
                is_cmd, handler = self.command_router.route(text)
                if is_cmd and handler:
                    logger.info(f"路由到命令处理 {request_id}")
                    context = {"request_id": request_id, "user": payload.get("user")}
                    return handler(text, context)
            
            # AI 核心处理
            if self.ai_core:
                return self.ai_core.chat(text, timeout=self.reply_timeout)
            
            logger.warning("未配置 AI 核心，无法处理查询")
            return "系统未配置 AI 核心"
        
        except Exception as e:
            logger.exception(f"请求处理异常 {request_id}")
            raise e
    
    def _handle_processing_result(self, request_id: str, future):
        """异步任务完成回调处理"""
        try:
            with self.request_lock:
                if request_id not in self.active_requests:
                    logger.warning(f"请求 {request_id} 结果回调时已不存在")
                    return
                if self.active_requests[request_id]["state"] != ProcessingState.PROCESSING:
                    logger.warning(f"请求 {request_id} 状态异常: {self.active_requests[request_id]['state']}")
                    return
            
            result = future.result()
            
            with self.request_lock:
                self.active_requests[request_id]["state"] = ProcessingState.COMPLETED
                self.active_requests[request_id]["result"] = result
                self.active_requests[request_id]["end_time"] = time.time()
            
            # 发布查询成功事件
            event_bus.publish("QUERY_RESULT", {
                "request_id": request_id,
                "result": result,
                "status": "success"
            })
            
            self.health_monitor.record_success()
            self.circuit_breaker.record_success()
            logger.info(f"请求 {request_id} 完成")
            
        except Exception as e:
            self._handle_processing_error(request_id, e)
    
    def _handle_processing_error(self, request_id: str, error: Exception):
        """任务执行错误处理"""
        with self.request_lock:
            if request_id not in self.active_requests:
                logger.warning(f"请求 {request_id} 错误处理时已不存在")
                return
            if self.active_requests[request_id]["state"] != ProcessingState.PROCESSING:
                logger.warning(f"请求 {request_id} 错误处理时状态异常: {self.active_requests[request_id]['state']}")
                return
            
            self.active_requests[request_id]["state"] = ProcessingState.FAILED
            self.active_requests[request_id]["error"] = str(error)
            self.active_requests[request_id]["end_time"] = time.time()
        
        logger.error(f"请求 {request_id} 失败: {str(error)}")
        
        event_bus.publish("QUERY_ERROR", {
            "request_id": request_id,
            "error": str(error),
            "status": "failed"
        })
        
        self.health_monitor.record_failure()
        self.circuit_breaker.record_failure()
    
    def _reject_request(self, payload: Dict[str, Any], reason: str):
        """拒绝请求并发布拒绝事件"""
        if event_bus is None:
            logger.warning("事件总线未初始化，拒绝请求无法发布事件")
            return
        event_bus.publish("QUERY_REJECTED", {
            "text": payload.get("text", ""),
            "user": payload.get("user", "anonymous"),
            "reason": reason,
            "timestamp": time.time()
        })
        self.health_monitor.record_rejection()
        if reason == "circuit_broken":
            self.circuit_breaker.record_failure()
    
    def handle_health_check(self, payload: Dict[str, Any]):
        """处理健康检查事件，发布状态信息"""
        if event_bus is None:
            logger.warning("事件总线未初始化，无法处理健康检查事件")
            return

        logger.debug("处理健康检查请求")
        
        with self.request_lock:
            health_info = {
                "service": "ReplyDispatcher",
                "active_requests": len(self.active_requests),
                "circuit_breaker_state": self.circuit_breaker.state if self.circuit_breaker else "unknown",
                "failure_rate": getattr(self.health_monitor, "current_failure_rate", 0),
                "queue_utilization": getattr(self.health_monitor, "queue_utilization", 0),
                "is_overloaded": getattr(self.health_monitor, "is_overloaded", False),
                "timestamp": time.time(),
                "requests": [
                    {
                        "id": rid,
                        "state": info["state"].value,
                        "age": time.time() - info["start_time"]
                    }
                    for rid, info in self.active_requests.items()
                ]
            }
        try:
            event_bus.publish("HEALTH_STATUS", health_info)
        except Exception as e:
            logger.error(f"发布健康状态失败: {e}")

    def _monitor_requests(self):
        """监控请求状态，超时处理和清理过期请求"""
        logger.info("启动请求监控线程")
        while True:
            try:
                now = time.time()
                timed_out = []
                
                with self.request_lock:
                    for rid, info in self.active_requests.items():
                        if info["state"] == ProcessingState.PROCESSING:
                            duration = now - info["start_time"]
                            if duration > self.reply_timeout:
                                info["state"] = ProcessingState.TIMEOUT
                                info["error"] = "请求处理超时"
                                info["end_time"] = now
                                timed_out.append(rid)
                
                for rid in timed_out:
                    logger.warning(f"请求超时: {rid}")
                    if event_bus:
                        event_bus.publish("QUERY_TIMEOUT", {"request_id": rid, "timeout": self.reply_timeout})
                    self.health_monitor.record_failure()
                    self.circuit_breaker.record_failure()
                
                with self.request_lock:
                    to_remove = [
                        rid for rid, info in self.active_requests.items()
                        if info["state"] in (ProcessingState.COMPLETED, ProcessingState.FAILED, ProcessingState.TIMEOUT)
                        and now - info.get("end_time", now) > 60
                    ]
                    for rid in to_remove:
                        del self.active_requests[rid]
                
                time.sleep(5)
                
            except Exception as e:
                logger.exception(f"监控线程异常: {str(e)}")
                time.sleep(10)
    
    def _periodic_health_report(self):
        """定期发布健康报告"""
        logger.info("启动健康报告线程")
        while True:
            try:
                self.handle_health_check({})
                time.sleep(getattr(config, "HEALTH_REPORT_INTERVAL", 60))
            except Exception as e:
                logger.exception(f"健康报告异常: {str(e)}")
                time.sleep(30)
    
    def shutdown(self):
        """安全关闭调度器，释放线程池和资源"""
        logger.info("关闭回复调度器")
        self.executor.shutdown(wait=True)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        if self._health_report_thread and self._health_report_thread.is_alive():
            self._health_report_thread.join(timeout=5)
        with self.request_lock:
            self.active_requests.clear()
        logger.info("回复调度器已关闭")
