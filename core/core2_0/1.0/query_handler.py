import logging
import threading
import time
from typing import Dict, Any, Optional, Union, Callable
from concurrent.futures import ThreadPoolExecutor, Future
from enum import Enum, auto
from contextlib import suppress
import uuid

from core.core2_0.utils.event_bus import subscribe_event, publish_event
from core.core2_0.aicore import AICore
from core.core2_0.utils.metrics import MetricsCollector
from modules.query_handler.manifest import MODULE_NAME

# 默认模块配置参数
DEFAULT_CONFIG = {
    "model_name": "default",
    "api_key": None,
    "max_tokens": 512,
    "temperature": 0.7,
    "max_workers": 4,
    "health_check_interval": 300,  # 秒
    "max_failures": 3,
    "timeout": 10,  # AI调用超时秒数
    "max_retries": 5,  # 健康检查最大重试次数
    "shutdown_timeout": 15,  # 关闭超时时间
}

logger = logging.getLogger(MODULE_NAME)

ModuleConfig = Dict[str, Union[str, int, float, bool, None]]


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
        """检查状态是否允许处理请求"""
        return state in [cls.READY, cls.PROCESSING, cls.DEGRADED]


class QueryHandler:
    """企业级查询处理模块，负责处理用户查询并生成AI响应"""

    def __init__(self, config: ModuleConfig):
        self.config = self._validate_config({**DEFAULT_CONFIG, **config})
        self.state = ModuleState.INITIALIZING
        self.ai_core: Optional[AICore] = None
        self.metrics = MetricsCollector(MODULE_NAME)
        self.thread_pool = ThreadPoolExecutor(
            max_workers=self.config["max_workers"],
            thread_name_prefix=f"{MODULE_NAME}-Worker"
        )
        self.last_health_check = time.time()
        self.failure_count = 0
        self.total_queries = 0
        self.lock = threading.RLock()
        self._health_check_timer: Optional[threading.Timer] = None
        self._health_check_retry_count = 0
        self._pending_tasks: Dict[str, Future] = {}
        self._event_handlers = {}

        try:
            self.initialize()
            logger.info(f"[{MODULE_NAME}] 模块初始化完成，状态: {self.state.name}")
        except Exception as e:
            self.state = ModuleState.ERROR
            logger.exception(f"[{MODULE_NAME}] 模块初始化失败: %s", e)
            raise

    def _validate_config(self, config: ModuleConfig) -> ModuleConfig:
        """验证并规范化配置参数"""
        if not config.get("api_key"):
            logger.warning(f"[{MODULE_NAME}] API密钥未配置，部分功能可能受限")
        
        # 确保温度参数在有效范围内
        config["temperature"] = max(0.0, min(1.0, float(config["temperature"])))
        
        # 确保超时时间合理
        config["timeout"] = max(1, int(config["timeout"]))
        
        # 确保最大重试次数合理
        config["max_retries"] = max(1, int(config.get("max_retries", 5)))
        
        # 确保关闭超时时间合理
        config["shutdown_timeout"] = max(5, int(config.get("shutdown_timeout", 15)))
        
        return config

    def initialize(self):
        """初始化模块资源"""
        try:
            logger.info(f"[{MODULE_NAME}] 正在初始化AI核心...")
            self.ai_core = AICore(
                model_name=self.config["model_name"],
                api_key=self.config["api_key"],
                max_tokens=self.config["max_tokens"],
                temperature=self.config["temperature"],
            )

            logger.info(f"[{MODULE_NAME}] 执行连接测试...")
            if not self.test_connection():
                self.state = ModuleState.ERROR
                logger.error(f"[{MODULE_NAME}] AI核心连接测试失败")
                return

            with self.lock:
                self.state = ModuleState.READY
                self._health_check_retry_count = 0

            logger.info(f"[{MODULE_NAME}] AI核心初始化成功")
            self.schedule_health_check()
            logger.info(f"[{MODULE_NAME}] 健康检查定时器已启动")

        except Exception as e:
            with self.lock:
                self.state = ModuleState.ERROR
            logger.exception(f"[{MODULE_NAME}] 初始化失败: %s", e)
            raise

    def test_connection(self) -> bool:
        """测试AI核心连接是否正常"""
        try:
            logger.debug(f"[{MODULE_NAME}] 执行连接测试...")
            test_response = self.ai_core.chat(
                "测试连接",
                max_tokens=5,
                timeout=self.config["timeout"]
            )
            success = bool(test_response)
            log_level = logging.INFO if success else logging.ERROR
            logger.log(log_level, f"[{MODULE_NAME}] 连接测试{'成功' if success else '失败'}")
            return success
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] 连接测试失败: %s", e)
            return False

    def schedule_health_check(self):
        """安排定时健康检查任务"""
        with self.lock:
            if self._health_check_timer:
                with suppress(Exception):
                    self._health_check_timer.cancel()

            # 在关闭或终止状态下不安排健康检查
            if self.state in [ModuleState.SHUTTING_DOWN, ModuleState.TERMINATED]:
                logger.debug(f"[{MODULE_NAME}] 当前状态 {self.state.name} 不安排健康检查")
                return

            interval = self.config["health_check_interval"]
            # 指数退避：失败时加倍延迟，最多10倍
            if self.state == ModuleState.ERROR:
                backoff_factor = min(2 ** self._health_check_retry_count, 10)
                interval = int(interval * backoff_factor)
                logger.debug(f"[{MODULE_NAME}] 错误状态下健康检查间隔调整为 {interval} 秒")

            logger.debug(f"[{MODULE_NAME}] 安排下一次健康检查，间隔: {interval}秒")
            self._health_check_timer = threading.Timer(interval, self.periodic_health_check)
            self._health_check_timer.daemon = True
            self._health_check_timer.start()

    def periodic_health_check(self):
        """定期健康检查"""
        try:
            logger.debug(f"[{MODULE_NAME}] 执行定期健康检查...")

            with self.lock:
                current_state = self.state
                
                # 在关闭或终止状态下跳过健康检查
                if current_state in [ModuleState.SHUTTING_DOWN, ModuleState.TERMINATED]:
                    logger.info(f"[{MODULE_NAME}] 模块正在关闭，跳过健康检查")
                    return

                # 尝试从错误状态恢复
                if current_state == ModuleState.ERROR:
                    if self._health_check_retry_count >= self.config["max_retries"]:
                        logger.error(f"[{MODULE_NAME}] 达到最大健康检查重试次数，保持错误状态")
                        self.schedule_health_check()
                        return

                    logger.warning(f"[{MODULE_NAME}] 尝试从错误状态恢复，重试次数 {self._health_check_retry_count + 1}")
                    self._health_check_retry_count += 1
                    self.initialize()
                    self.schedule_health_check()
                    return

                # 执行健康检查
                is_healthy = self.test_connection()
                self.last_health_check = time.time()

                if not is_healthy:
                    self.failure_count += 1
                    logger.warning(f"[{MODULE_NAME}] 健康检查失败，服务降级 (失败次数: {self.failure_count})")
                    
                    if self.failure_count >= self.config["max_failures"]:
                        logger.error(f"[{MODULE_NAME}] 连续健康检查失败，进入错误状态")
                        self.state = ModuleState.ERROR
                    else:
                        self.state = ModuleState.DEGRADED
                else:
                    if current_state != ModuleState.READY:
                        logger.info(f"[{MODULE_NAME}] 健康检查通过，恢复就绪状态")
                    self.failure_count = 0
                    self.state = ModuleState.READY

            # 发布健康状态更新事件
            self.publish_event_safe("MODULE_HEALTH_UPDATE", {
                "module": MODULE_NAME,
                "status": self.state.name,
                "last_health_check": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_health_check)),
                "failure_count": self.failure_count,
            })

        except Exception as e:
            logger.exception(f"[{MODULE_NAME}] 健康检查异常: %s", e)
        finally:
            self.schedule_health_check()

    def get_module_status(self) -> Dict[str, Any]:
        """获取模块状态信息"""
        with self.lock:
            return {
                "name": MODULE_NAME,
                "status": self.state.name,
                "health": (
                    "good" if self.state == ModuleState.READY else
                    "degraded" if self.state in [ModuleState.DEGRADED, ModuleState.PROCESSING] else
                    "error"
                ),
                "metrics": self.metrics.get_metrics(),
                "last_health_check": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_health_check)),
                "total_queries": self.total_queries,
                "active_tasks": len(self._pending_tasks),
                "failure_count": self.failure_count,
                "config": {
                    k: "***" if "key" in k.lower() or "secret" in k.lower() else v 
                    for k, v in self.config.items()
                }
            }

    def process_query(self, event_data: dict):
        """处理查询请求（线程池调用入口）"""
        query_id = event_data.get("query_id", f"qry-{uuid.uuid4().hex[:8]}")
        try:
            self.metrics.start_timer("query_processing")

            # 验证事件数据
            if not isinstance(event_data, dict):
                logger.warning(f"[{MODULE_NAME}] 非法事件数据: {event_data}")
                self.metrics.increment_counter("invalid_events")
                return

            text = event_data.get("text", "").strip()
            source = event_data.get("source", "unknown")

            if not text:
                logger.warning(f"[{MODULE_NAME}] 空查询内容，忽略处理 (来源: {source}, ID: {query_id})")
                self.metrics.increment_counter("empty_queries")
                return

            truncated_text = text[:30] + ('...' if len(text) > 30 else '')
            logger.info(f"[{MODULE_NAME}] 处理查询: '{truncated_text}' (来源: {source}, ID: {query_id})")
            self.metrics.increment_counter("queries_received")

            # 检查模块状态
            with self.lock:
                if not ModuleState.is_active(self.state):
                    error_msg = f"模块状态 {self.state.name} 不可用"
                    logger.error(f"[{MODULE_NAME}] {error_msg}")
                    self.metrics.increment_counter("service_unavailable")

                    self.publish_event_safe("QUERY_RESPONSE", {
                        "source": MODULE_NAME,
                        "response": "⚠️ 查询服务暂时不可用，请稍后重试。",
                        "original_query": text,
                        "target": source,
                        "query_id": query_id,
                        "success": False,
                        "error": error_msg
                    })
                    return

                # 标记为处理中状态（如果当前是就绪状态）
                if self.state == ModuleState.READY:
                    self.state = ModuleState.PROCESSING

            # 实际处理逻辑
            try:
                response = self.ai_core.chat(
                    text,
                    max_tokens=self.config["max_tokens"],
                    temperature=self.config["temperature"],
                    timeout=self.config["timeout"],
                )

                logger.info(f"[{MODULE_NAME}] 响应生成成功 (ID: {query_id})")
                self.metrics.increment_counter("queries_success")

                # 发布响应事件
                self.publish_event_safe("QUERY_RESPONSE", {
                    "source": MODULE_NAME,
                    "response": response,
                    "original_query": text,
                    "target": source,
                    "query_id": query_id,
                    "success": True
                })

            except Exception as e:
                logger.exception(f"[{MODULE_NAME}] 查询处理出错 (ID: {query_id}): %s", e)
                self.metrics.increment_counter("processing_errors")

                self.publish_event_safe("QUERY_RESPONSE", {
                    "source": MODULE_NAME,
                    "response": "⚠️ 系统处理失败，请稍后重试。",
                    "original_query": text,
                    "target": source,
                    "query_id": query_id,
                    "success": False,
                    "error": str(e)
                })

            finally:
                # 恢复状态（如果是最后一个处理中的任务）
                with self.lock:
                    if self.state == ModuleState.PROCESSING:
                        self.state = ModuleState.READY
                
                # 从待处理任务中移除
                with suppress(KeyError):
                    del self._pending_tasks[query_id]
                
                # 更新统计信息
                self.total_queries += 1
                self.metrics.stop_timer("query_processing")

        except Exception as e:
            logger.exception(f"[{MODULE_NAME}] 查询处理流程异常 (ID: {query_id}): %s", e)
            self.metrics.increment_counter("system_errors")
    
    def publish_event_safe(self, event_name: str, data: Any):
        """安全调用事件发布，捕获异常防止崩溃"""
        try:
            publish_event(event_name, data)
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] 发布事件 {event_name} 失败: {e}")

    def shutdown(self):
        """安全关闭模块"""
        with self.lock:
            if self.state == ModuleState.TERMINATED:
                return

            logger.info(f"[{MODULE_NAME}] 开始关闭模块...")
            self.state = ModuleState.SHUTTING_DOWN

            # 取消健康检查定时器
            if self._health_check_timer:
                with suppress(Exception):
                    self._health_check_timer.cancel()
                self._health_check_timer = None

            # 取消所有待处理任务
            logger.info(f"[{MODULE_NAME}] 取消 {len(self._pending_tasks)} 个待处理查询任务")
            for task_id, task in self._pending_tasks.items():
                with suppress(Exception):
                    task.cancel()
            self._pending_tasks.clear()

            # 关闭线程池
            logger.info(f"[{MODULE_NAME}] 关闭线程池...")
            self.thread_pool.shutdown(
                wait=True, 
                timeout=self.config["shutdown_timeout"]
            )

            # 释放AI核心资源
            if self.ai_core:
                try:
                    self.ai_core.close()
                except (AttributeError, NotImplementedError) as e:
                    logger.debug(f"[{MODULE_NAME}] AI核心关闭方法不可用: {e}")
                self.ai_core = None

            # 清理事件订阅
            logger.info(f"[{MODULE_NAME}] 清理事件订阅...")
            for event_type, handler in self._event_handlers.items():
                with suppress(Exception):
                    # 假设事件总线有取消订阅的方法
                    unsubscribe_event(event_type, handler)

            self.state = ModuleState.TERMINATED
            logger.info(f"[{MODULE_NAME}] 模块已安全关闭")


_query_handler_instance: Optional[QueryHandler] = None


def get_query_handler(config: ModuleConfig) -> QueryHandler:
    global _query_handler_instance
    if _query_handler_instance is None:
        _query_handler_instance = QueryHandler(config)
    return _query_handler_instance


def handle_user_query(event_data: dict):
    global _query_handler_instance
    if _query_handler_instance is None:
        logger.error(f"[{MODULE_NAME}] 模块未初始化，无法处理查询")
        return

    # 确保有唯一查询ID
    if "query_id" not in event_data:
        event_data["query_id"] = f"qry-{uuid.uuid4().hex[:8]}"

    try:
        # 提交任务并跟踪
        future = _query_handler_instance.thread_pool.submit(
            _query_handler_instance.process_query,
            event_data
        )
        # 记录待处理任务
        _query_handler_instance._pending_tasks[event_data["query_id"]] = future
    except RuntimeError as e:
        # 线程池已关闭
        logger.error(f"[{MODULE_NAME}] 无法提交查询任务 (ID: {event_data.get('query_id', 'unknown')}): {e}")
        _query_handler_instance.publish_event_safe("QUERY_RESPONSE", {
            "source": MODULE_NAME,
            "response": "⚠️ 系统正在关闭，无法处理新请求。",
            "original_query": event_data.get("text", ""),
            "target": event_data.get("source", "unknown"),
            "query_id": event_data.get("query_id", "unknown"),
            "success": False,
            "error": "Service shutting down"
        })
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] 提交查询任务失败: {e}")


def register_actions(config: ModuleConfig):
    """模块初始化和事件注册"""
    try:
        logger.info(f"[{MODULE_NAME}] 正在初始化查询处理模块...")
        handler = get_query_handler(config)
        
        # 定义事件处理函数
        def user_query_handler(data):
            handle_user_query(data)
        
        def status_request_handler(data):
            handler.publish_event_safe("MODULE_STATUS_RESPONSE", {
                "module": MODULE_NAME,
                "status": handler.get_module_status()
            })
        
        def unload_handler(data):
            if data.get("module") == MODULE_NAME:
                logger.info(f"[{MODULE_NAME}] 收到卸载请求")
                handler.shutdown()
                # 清理全局实例
                global _query_handler_instance
                _query_handler_instance = None
                handler.publish_event_safe("MODULE_UNLOADED", {"module": MODULE_NAME})
        
        # 注册事件并保存处理器引用
        handler._event_handlers["USER_QUERY"] = subscribe_event("USER_QUERY", user_query_handler)
        handler._event_handlers["MODULE_STATUS_REQUEST"] = subscribe_event("MODULE_STATUS_REQUEST", status_request_handler)
        handler._event_handlers["MODULE_UNLOAD_REQUEST"] = subscribe_event("MODULE_UNLOAD_REQUEST", unload_handler)

        logger.info(f"[{MODULE_NAME}] 成功注册事件监听器")
        logger.info(f"[{MODULE_NAME}] 模块已启动并准备就绪")

        return handler

    except Exception as e:
        logger.exception(f"[{MODULE_NAME}] 模块注册失败: %s", e)
        # 清理部分初始化的资源
        global _query_handler_instance
        if _query_handler_instance:
            with suppress(Exception):
                _query_handler_instance.shutdown()
            _query_handler_instance = None
        raise
