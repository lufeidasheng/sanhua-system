import logging
import threading
import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, Dict, Optional, Any, Tuple, List
from functools import lru_cache, wraps
from datetime import datetime, timedelta
from uuid import uuid4
from contextlib import contextmanager
from Levenshtein import ratio  # 确保已安装 python-Levenshtein

# 日志配置
log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('action_dispatcher.log', encoding='utf-8')
    ]
)

class ActionPriority(Enum):
    CRITICAL = auto()
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()

@dataclass
class ActionDependency:
    name: str
    input_mapper: Callable[[Any], Tuple] = field(default=lambda *args, **kwargs: (args, kwargs))
    required: bool = True

@dataclass
class ActionMetadata:
    func: Callable
    module: str
    description: str = "No description"
    signature: str = "No signature info"
    priority: ActionPriority = ActionPriority.NORMAL
    permission: str = "user"
    timeout: float = 5.0
    last_executed: Optional[datetime] = None
    dependencies: List[ActionDependency] = field(default_factory=list)
    circuit_breaker: Dict[str, Any] = field(default_factory=lambda: {
        "failure_count": 0,
        "last_failure": None,
        "disabled_until": None,
        "success_count": 0
    })

class QuantumActionDispatcher:
    def __init__(self, max_workers: int = 8, circuit_breaker_threshold: int = 3, 
                 recovery_threshold: int = 5, log_level=logging.INFO):
        self._registry: Dict[str, ActionMetadata] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ActionWorker"
        )
        self._async_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="AsyncActionWorker"
        )
        self._lock = threading.RLock()
        self._metrics = {
            "total_actions": 0,
            "failed_actions": 0,
            "circuit_triggered": 0,
            "successful_actions": 0
        }
        self._context = {}
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._recovery_threshold = recovery_threshold
        self._pending_tasks = 0
        self._task_lock = threading.Lock()
        self._shutdown_flag = False

        log.setLevel(log_level)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def shutdown(self):
        """Gracefully shutdown the dispatcher"""
        self._shutdown_flag = True
        self._executor.shutdown(wait=True)
        self._async_executor.shutdown(wait=True)
        self._monitor_thread.join(timeout=1)

    def _monitor_loop(self):
        """Monitor system health and metrics"""
        while not self._shutdown_flag:
            with self._task_lock:
                load = self._pending_tasks
                total_actions = len(self._registry)
                active_workers = self._executor._max_workers

            metrics = {
                "load": load,
                "active_workers": active_workers,
                "registered_actions": total_actions,
                "success_rate": self._metrics["successful_actions"] / 
                               (self._metrics["successful_actions"] + self._metrics["failed_actions"] + 1e-6)
            }
            log.info("System Metrics: %s", json.dumps(metrics, default=str))
            time.sleep(10)

    def register_action(self, name: str, **options):
        """Decorator to register an action with options"""
        def decorator(func):
            docstring = func.__doc__ or "No description"
            description = options.get("description", docstring.split('\n')[0].strip())
            self.register(
                name, func,
                module=options.get("module", "global"),
                description=description,
                signature=options.get("signature", str(func.__annotations__)),
                priority=options.get("priority", ActionPriority.NORMAL),
                timeout=options.get("timeout", 5.0),
                permission=options.get("permission", "user"),
                dependencies=options.get("dependencies", [])
            )
            log.info(f"Action '{name}' registered successfully")
            func._action_name = name
            func._action_metadata = self._registry[name]
            return func
        return decorator

    def register(self, name: str, func: Callable, *,
                 module: str = "global",
                 description: str = "No description",
                 signature: str = "No signature info",
                 priority: ActionPriority = ActionPriority.NORMAL,
                 permission: str = "user",
                 timeout: float = 5.0,
                 dependencies: List[ActionDependency] = None):
        with self._lock:
            self._registry[name] = ActionMetadata(
                func=func,
                module=module,
                description=description,
                signature=signature,
                priority=priority,
                permission=permission,
                timeout=timeout,
                dependencies=dependencies or []
            )
            self._metrics["total_actions"] = len(self._registry)
            log.info(f"🌀 Registered action [{priority.name}] {name}")

    def unregister(self, name: str) -> bool:
        with self._lock:
            removed = self._registry.pop(name, None) is not None
            if removed:
                self._metrics["total_actions"] = len(self._registry)
            return removed

    def clear_actions_by_module(self, module_name: str) -> int:
        count = 0
        with self._lock:
            to_remove = [name for name, meta in self._registry.items() if meta.module == module_name]
            for name in to_remove:
                self._registry.pop(name, None)
                count += 1
            self.match.cache_clear()
            self._metrics["total_actions"] = len(self._registry)
        log.info(f"🧹 Cleared {count} actions from module {module_name}")
        return count

    @lru_cache(maxsize=2048)
    def match(self, query: str, *, threshold: float = 0.85) -> Optional[Tuple[str, float]]:
        query = query.lower().strip().replace("  ", " ")
        candidates = []
        with self._lock:
            for name, meta in self._registry.items():
                if self._is_circuit_broken(name):
                    continue
                if name.lower() == query:
                    return (name, 1.0)
                sim_score = ratio(name.lower(), query)
                if sim_score >= threshold:
                    candidates.append((name, sim_score))
        return max(candidates, key=lambda x: x[1]) if candidates else None

    def _is_circuit_broken(self, name: str) -> bool:
        meta = self._registry.get(name)
        if not meta:
            return False
        cb = meta.circuit_breaker
        if cb["disabled_until"] and datetime.now() < cb["disabled_until"]:
            return True
        if cb["last_failure"] and (datetime.now() - cb["last_failure"]) > timedelta(minutes=5):
            cb["failure_count"] = 0
            cb["disabled_until"] = None
        return False

    def _update_circuit_breaker(self, name: str, success: bool):
        with self._lock:
            meta = self._registry.get(name)
            if not meta:
                return
            cb = meta.circuit_breaker
            if success:
                cb["success_count"] += 1
                cb["failure_count"] = max(0, cb["failure_count"] - 0.5)
                if cb["success_count"] >= self._recovery_threshold:
                    cb.update({
                        "failure_count": 0,
                        "disabled_until": None,
                        "success_count": 0
                    })
                    log.info(f"Circuit for action '{name}' fully recovered")
            else:
                cb["failure_count"] += 1
                cb["success_count"] = 0
                cb["last_failure"] = datetime.now()
                if cb["failure_count"] >= self._circuit_breaker_threshold:
                    cb["disabled_until"] = datetime.now() + timedelta(minutes=5)
                    self._metrics["circuit_triggered"] += 1
                    log.warning(f"Circuit opened for action '{name}' (failures: {cb['failure_count']})")

    @contextmanager
    def _contextual_execution(self, trace_id: str):
        old_context = self._context.copy()
        self._context["trace_id"] = trace_id
        self._context["start_time"] = datetime.now()
        try:
            yield
        finally:
            self._context = old_context

    def _execute_with_timeout(self, func, args, kwargs, timeout, trace_id):
        result = None
        exception = None
        start = datetime.now()

        def _worker():
            nonlocal result, exception
            try:
                with self._contextual_execution(trace_id):
                    result = func(*args, **kwargs)
            except Exception as e:
                exception = e
                log.exception(f"Action execution failed: {str(e)}")

        worker = threading.Thread(target=_worker, name=f"ActionThread-{trace_id}")
        worker.daemon = True
        worker.start()
        worker.join(timeout=timeout)

        exec_time = (datetime.now() - start).total_seconds()
        log_extra = {
            "trace_id": trace_id,
            "execution_time": exec_time,
            "status": "success" if exception is None else "failed"
        }
        log.info("Action execution completed", extra=log_extra)

        if exception:
            raise exception
        if worker.is_alive():
            raise TimeoutError(f"Action timed out after {timeout}s")
        return result

    def execute(self, name: str, *args, **kwargs) -> Any:
        with self._lock:
            meta = self._registry.get(name)
            if not meta:
                raise KeyError(f"Unknown action: {name}")
            if self._is_circuit_broken(name):
                raise RuntimeError(f"Action {name} is in circuit breaker open state")

        current_load = self._pending_tasks / (self._executor._max_workers * 2)
        adjusted_timeout = meta.timeout * (1 + current_load * 0.1)

        dep_results = {}
        for dep in meta.dependencies:
            try:
                dep_args, dep_kwargs = dep.input_mapper(*args, **kwargs)
                dep_results[dep.name] = self.execute(dep.name, *dep_args, **dep_kwargs)
            except Exception as e:
                log.error(f"Dependency action {dep.name} failed: {str(e)}")
                raise RuntimeError(f"Dependency action failed: {dep.name}") from e

        kwargs = {**kwargs, **dep_results}

        try:
            with self._track_task():
                future = self._executor.submit(
                    self._execute_with_timeout,
                    meta.func,
                    args,
                    kwargs,
                    min(adjusted_timeout, meta.timeout * 3),
                    f"trace-{uuid4().hex[:8]}"
                )
                result = future.result()
                self._update_circuit_breaker(name, success=True)
                self._metrics["successful_actions"] += 1
                meta.last_executed = datetime.now()
                return result
        except Exception as e:
            self._metrics["failed_actions"] += 1
            self._update_circuit_breaker(name, success=False)
            raise

    async def execute_async(self, name: str, *args, **kwargs) -> Any:
        with self._lock:
            meta = self._registry.get(name)
            if not meta:
                raise KeyError(f"Unknown action: {name}")
            if self._is_circuit_broken(name):
                raise RuntimeError(f"Action {name} is in circuit breaker open state")

        if asyncio.iscoroutinefunction(meta.func):
            try:
                with self._track_task():
                    return await asyncio.wait_for(meta.func(*args, **kwargs), timeout=meta.timeout)
            except asyncio.TimeoutError:
                self._update_circuit_breaker(name, success=False)
                raise TimeoutError(f"Async action timed out after {meta.timeout}s")
        else:
            loop = asyncio.get_running_loop()
            try:
                with self._track_task():
                    return await loop.run_in_executor(
                        self._async_executor,
                        lambda: self.execute(name, *args, **kwargs)
                    )
            except Exception:
                self._update_circuit_breaker(name, success=False)
                raise

    def action(self, name: str, **options):
        def decorator(f):
            self.register_action(name, **options)(f)

            @wraps(f)
            async def async_wrapper(*args, **kwargs):
                return await self.execute_async(name, *args, **kwargs)

            setattr(f, "async_execute", async_wrapper)
            return f
        return decorator

    async def execute_batch(self, actions: List[Tuple[str, Tuple, Dict]]) -> Dict[str, Any]:
        tasks = []
        results = {}
        loop = asyncio.get_event_loop()

        for name, args, kwargs in actions:
            if name not in self._registry:
                results[name] = {"error": f"Unknown action: {name}"}
                continue
            if asyncio.iscoroutinefunction(self._registry[name].func):
                tasks.append(self.execute_async(name, *args, **kwargs))
            else:
                tasks.append(loop.run_in_executor(
                    self._async_executor,
                    lambda: self.execute(name, *args, **kwargs)
                ))

        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for (name, _, _), result in zip(actions, completed):
            results[name] = result if not isinstance(result, Exception) else {"error": str(result)}

        return results

    def get_action_info(self, name: str) -> Optional[Dict]:
        with self._lock:
            meta = self._registry.get(name)
            if not meta:
                return None
            return {
                "name": name,
                "module": meta.module,
                "description": meta.description,
                "signature": meta.signature,
                "timeout": meta.timeout,
                "permission": meta.permission,
                "last_executed": meta.last_executed,
                "circuit_status": "open" if self._is_circuit_broken(name) else "closed",
                "dependencies": [dep.name for dep in meta.dependencies]
            }

    def list_actions(self, module: Optional[str] = None) -> List[Dict]:
        with self._lock:
            return [
                self.get_action_info(name)
                for name, meta in self._registry.items()
                if module is None or meta.module == module
            ]

    def clear_actions_by_module(self, module_name: str) -> int:
        count = 0
        with self._lock:
            to_remove = [name for name, meta in self._registry.items() if meta.module == module_name]
            for name in to_remove:
                self._registry.pop(name, None)
                count += 1
            self.match.cache_clear()
        log.info(f"🧹 Cleared {count} actions from module {module_name}")
        return count


# 全局实例与注册器
_global_dispatcher: Optional[QuantumActionDispatcher] = None

def get_global_dispatcher() -> QuantumActionDispatcher:
    global _global_dispatcher
    if _global_dispatcher is None:
        _global_dispatcher = QuantumActionDispatcher()
    return _global_dispatcher

dispatcher = get_global_dispatcher()
register_action = dispatcher.register_action
clear_actions_by_module = dispatcher.clear_actions_by_module

def execute_action(name: str, *args, **kwargs):
    return dispatcher.execute(name, *args, **kwargs)

def list_actions(module: Optional[str] = None):
    return dispatcher.list_actions(module)

__all__ = [
    "dispatcher",
    "register_action",
    "clear_actions_by_module",
    "execute_action",
    "list_actions",
]
