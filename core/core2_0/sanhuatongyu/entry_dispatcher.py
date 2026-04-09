"""
三花聚顶 · 企业级入口调度控制器 (Fedora强化版)
"""

import os
import time
import signal
import threading
import ctypes
import importlib.util
from types import ModuleType
from typing import Dict, Tuple, Callable, Optional, Any
from importlib import import_module
from functools import partial
from contextlib import contextmanager

from core.core2_0.sanhuatongyu.logger import get_logger  # 🚀 融合增强日志系统
from core.core2_0.sanhuatongyu.monitoring.metrics import PrometheusExporter

try:
    from core.core2_0.utils import exponential_backoff
except ImportError:
    def exponential_backoff(max_retries=3, base_delay=1, max_delay=30):
        def decorator(func): return func
        return decorator

class CriticalEntryFailure(Exception): pass
class SecurityException(Exception): pass

class EnterpriseEntryDispatcher:
    """
    企业级入口调度控制器
    负责入口模块注册、事件订阅、动态入口选择、入口调用、熔断容灾、日志和监控。
    """

    _ENTRY_REGISTRY: Dict[str, Tuple[str, int]] = {}
    _CIRCUIT_BREAKER_STATE = "closed"
    _CIRCUIT_BREAKER_TRIPS = 0
    _CIRCUIT_BREAKER_LOCK = threading.Lock()

    @classmethod
    def register_entry(cls, name: str, module: str, priority: int = 100):
        if not name.isidentifier():
            raise ValueError(f"入口名称不合法: {name}")
        with cls._CIRCUIT_BREAKER_LOCK:
            cls._ENTRY_REGISTRY[name.lower()] = (module, priority)
            cls._ENTRY_REGISTRY = dict(
                sorted(cls._ENTRY_REGISTRY.items(), key=lambda x: x[1][1], reverse=True)
            )

    def __init__(
        self,
        system,
        entry_name: str,
        fallback_strategy: str = "priority",
        policy_check: bool = True,
        timeout: int = 30,
        fedora_enhanced: bool = True,
    ):
        self.system = system
        self.entry_name = entry_name.lower()
        self.policy_check = policy_check
        self.timeout = timeout
        self.logger = get_logger("entry_dispatcher")  # 🌟日志系统一键融合
        self.metrics = PrometheusExporter(port=8000)
        self.fallback_strategy = fallback_strategy
        self.fedora_enhanced = fedora_enhanced

        if not self._ENTRY_REGISTRY:
            self.register_entry("cli", "core.core2_0.cli_entry", 90)
            self.register_entry("gui", "core.core2_0.gui_entry", 80)
            self.register_entry("voice", "core.core2_0.voice_entry", 70)

        if self.fedora_enhanced:
            self._fedora_cert_check()
        if self.policy_check:
            self._perform_policy_check()

    def _fedora_cert_check(self):
        try:
            fedora_ca_path = "/etc/pki/tls/certs/ca-bundle.crt"
            if not os.path.exists(fedora_ca_path):
                self.logger.warning(
                    "fedora_ca_missing",
                    path=fedora_ca_path,
                    action="disable_tls_validation",
                )
                os.environ["CURL_CA_BUNDLE"] = ""
                os.environ["REQUESTS_CA_BUNDLE"] = ""
        except Exception as e:
            self.logger.error("cert_check_failed", error=str(e))

    def _perform_policy_check(self):
        try:
            module_dir = os.path.dirname(__file__)
            if not self._validate_selinux_context(module_dir):
                self.logger.warning(
                    "selinux_invalid", path=module_dir, action="fallback_to_cli"
                )
                self.entry_name = "cli"
        except Exception as e:
            self.logger.error("security_policy_check_failed", error=str(e))
            self.policy_check = False

    def _validate_selinux_context(self, path: str) -> bool:
        return True

    def _safe_callback(self, func: Callable):
        def wrapper(event_type, event_data):
            try:
                func(event_type, event_data)
            except Exception as e:
                self.logger.error("event_handler_error", error=str(e))
        return wrapper

    @exponential_backoff(max_retries=3, base_delay=1, max_delay=10)
    def attach(self):
        try:
            if (
                hasattr(self.system, "context")
                and hasattr(self.system.context, "event_bus")
                and self.system.context.event_bus.is_ready()
            ):
                self.system.context.event_bus.subscribe(
                    "MODULES_LOADED",
                    self._safe_callback(self._on_modules_ready),
                )
                self.logger.info("event_subscribe_success")
                self.metrics.register_counter(
                    "entry_dispatcher_attached", "入口调度器附加计数"
                )
                self.metrics.increment("entry_dispatcher_attached")
                return True
            else:
                self.logger.warning("event_bus_unavailable_direct_start")
                self._on_modules_ready("DIRECT_START", {})
                return True
        except Exception as e:
            self.logger.critical("event_subscribe_failed", error=str(e))
            self._emergency_start()
            return False

    def _on_modules_ready(self, event_type: str, event_data: dict):
        if self._CIRCUIT_BREAKER_STATE == "open":
            self.logger.warning("circuit_breaker_open")
            self._emergency_start()
            return
        start_time = time.monotonic()
        try:
            target_entry = self._select_entry_point()
            self._invoke_entry(target_entry)
        except CriticalEntryFailure as e:
            self.logger.critical("cascade_entry_failure", error=str(e))
            self._activate_circuit_breaker()
        except Exception as e:
            self.logger.error("entry_process_exception", error=str(e))
            self._activate_circuit_breaker()
        finally:
            latency = time.monotonic() - start_time
            self.metrics.observe("entry_dispatch_latency", latency)

    def _select_entry_point(self) -> str:
        if self._CIRCUIT_BREAKER_STATE == "half-open":
            self.logger.warning("circuit_breaker_half_open")
            return "cli"
        if self._is_entry_available(self.entry_name):
            return self.entry_name
        if self.fallback_strategy == "priority":
            for entry, (mod, pri) in self._ENTRY_REGISTRY.items():
                if entry != self.entry_name and self._is_entry_available(entry):
                    self.logger.warning(
                        "fallback_priority_switch", from_entry=self.entry_name, to_entry=entry
                    )
                    return entry
        elif self.fallback_strategy == "sequence":
            fallback_chain = ["gui", "cli", "voice"]
            for entry in fallback_chain:
                if self._is_entry_available(entry):
                    self.logger.warning(
                        "fallback_sequence_switch", from_entry=self.entry_name, to_entry=entry
                    )
                    return entry
        safest_entry = next(iter(self._ENTRY_REGISTRY))
        self.logger.critical(
            "final_fallback_entry", from_entry=self.entry_name, to_entry=safest_entry
        )
        return safest_entry

    def _is_entry_available(self, entry_name: str) -> bool:
        if entry_name not in self._ENTRY_REGISTRY:
            return False
        module_name = self._ENTRY_REGISTRY[entry_name][0]
        if not hasattr(self.system, "module_manager"):
            self.logger.error("no_module_manager")
            return False
        if not self._is_module_loaded(module_name):
            try:
                self.logger.info("try_dynamic_load_module", module=module_name)
                if not self.system.module_manager.load_single_module(module_name):
                    self.metrics.increment("module_load_failed", labels={"module": module_name})
                    return False
            except Exception as e:
                self.logger.error(
                    "module_load_exception", error=str(e), module=module_name
                )
                return False
        module = self.system.module_manager.get_module(module_name)
        return hasattr(module, "entry") and callable(module.entry)

    def _is_module_loaded(self, module_name: str) -> bool:
        if hasattr(self.system.module_manager, "loaded_modules"):
            return module_name in self.system.module_manager.loaded_modules
        elif hasattr(self.system.module_manager, "is_module_loaded"):
            return self.system.module_manager.is_module_loaded(module_name)
        else:
            return importlib.util.find_spec(module_name) is not None

    def _invoke_entry(self, entry_name: str):
        if entry_name not in self._ENTRY_REGISTRY:
            self.logger.error("entry_not_registered", entry=entry_name)
            raise ValueError(f"入口未注册: {entry_name}")

        module_name = self._ENTRY_REGISTRY[entry_name][0]

        if not self._is_module_loaded(module_name):
            self.logger.error("module_not_loaded", module=module_name)
            raise CriticalEntryFailure(f"模块未加载: {module_name}")

        module = self.system.module_manager.get_module(module_name)

        try:
            self.logger.info(
                "entry_exec_start",
                entry=entry_name,
                module=module_name,
                timeout=self.timeout,
            )
            with self._timeout_context(self.timeout):
                self.metrics.increment(
                    "entry_call_count", labels={"entry": entry_name}
                )
                start_time = time.perf_counter()
                module.entry()
                elapsed = time.perf_counter() - start_time
                self.metrics.observe(
                    "entry_exec_latency", elapsed, labels={"entry": entry_name}
                )
                if self._CIRCUIT_BREAKER_STATE == "half-open":
                    self._reset_circuit_breaker()
        except TimeoutError:
            self.logger.error(
                "entry_timeout", entry=entry_name, timeout=self.timeout
            )
            self.metrics.increment("entry_timeout_count", labels={"entry": entry_name})
            self._trip_circuit_breaker(entry_name)
        except SecurityException as e:
            self.logger.error(
                "entry_security_violation", entry=entry_name, error=str(e)
            )
            self.metrics.increment("security_violation_count")
            self._trip_circuit_breaker(entry_name)
            raise CriticalEntryFailure(f"{entry_name} 发生安全违规") from e
        except Exception as e:
            self.logger.error(
                "entry_exec_failed", error=str(e), entry=entry_name
            )
            self.metrics.increment("entry_failed_count", labels={"entry": entry_name})
            self._trip_circuit_breaker(entry_name)
            raise

    @contextmanager
    def _timeout_context(self, seconds: int):
        if threading.current_thread() is threading.main_thread():
            def timeout_handler(signum, frame):
                raise TimeoutError(f"操作超时，超过 {seconds} 秒")
            original_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, original_handler)
        else:
            timer = threading.Timer(
                seconds,
                lambda: ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(threading.get_ident()), ctypes.py_object(TimeoutError)
                ),
            )
            timer.start()
            try:
                yield
            finally:
                timer.cancel()

    def _trip_circuit_breaker(self, failed_entry=None):
        with self._CIRCUIT_BREAKER_LOCK:
            self._CIRCUIT_BREAKER_TRIPS += 1
            if self._CIRCUIT_BREAKER_TRIPS >= 3:
                self._CIRCUIT_BREAKER_STATE = "open"
                self.logger.critical(
                    "circuit_breaker_opened",
                    trips=self._CIRCUIT_BREAKER_TRIPS,
                    failed_entry=failed_entry,
                )
                threading.Timer(60.0, self._half_open_circuit).start()
            elif self._CIRCUIT_BREAKER_STATE == "closed":
                self.logger.warning(
                    "circuit_breaker_tripped",
                    trips=self._CIRCUIT_BREAKER_TRIPS,
                    failed_entry=failed_entry,
                )

    def _half_open_circuit(self):
        with self._CIRCUIT_BREAKER_LOCK:
            self._CIRCUIT_BREAKER_STATE = "half-open"
            self.logger.warning("circuit_breaker_half_open")

    def _reset_circuit_breaker(self):
        with self._CIRCUIT_BREAKER_LOCK:
            self._CIRCUIT_BREAKER_STATE = "closed"
            self._CIRCUIT_BREAKER_TRIPS = 0
            self.logger.info("circuit_breaker_reset")

    def _activate_circuit_breaker(self, failed_entry=None):
        self._trip_circuit_breaker(failed_entry)
        if hasattr(self.system, "enter_safe_mode"):
            try:
                self.system.enter_safe_mode()
                return
            except Exception as e:
                self.logger.error("safe_mode_failed", error=str(e))
        self._emergency_start()

    def _emergency_start(self):
        try:
            try:
                from core.core2_0.sanhuatongyu.emergency_cli import MinimalCLI
            except ImportError:
                from .emergency_cli import MinimalCLI

            cli = MinimalCLI(self.system)
            cli.start()
        except Exception as e:
            self.logger.critical(
                "emergency_cli_failed", error=str(e)
            )
            print("\n===== Fedora应急模式 =====")
            print("系统发生严重错误，进入应急模式")
            print(f"时间: {time.ctime()}")
            print(f"主机: {os.uname().nodename}")
            print("输入 'status' 查看系统状态")

            while True:
                try:
                    cmd = input("FEDORA-EMERGENCY> ")
                    if cmd == "exit":
                        break
                    elif cmd == "status":
                        print("\n[系统状态]")
                        print(
                            f"熔断器状态: {self._CIRCUIT_BREAKER_STATE} (触发次数: {self._CIRCUIT_BREAKER_TRIPS})"
                        )
                        print(f"可用入口列表: {list(self._ENTRY_REGISTRY.keys())}")
                        print(
                            f"事件总线状态: {'可用' if hasattr(self.system.context, 'event_bus') else '不可用'}"
                        )
                    else:
                        print(f"未知命令: {cmd}")
                except KeyboardInterrupt:
                    print("\n系统关闭")
                    os._exit(1)
                except Exception as e:
                    print(f"命令执行错误: {str(e)}")


if __name__ == "__main__":
    from core.core2_0.sanhuatongyu.master import SanHuaTongYu

    # 日志全局初始化
    from core.core2_0.sanhuatongyu.logger import configure_logging
    configure_logging(
        level="INFO",
        log_dir="logs",
        json_format=True,
        i18n_lang="zh_CN"
    )

    system = SanHuaTongYu(
        modules_dir="modules",
        global_config_path="config/global_config.yaml",
        user_config_path="config/user_config.yaml",
        dev_mode=True,
    )

    dispatcher = EnterpriseEntryDispatcher(system, entry_name="cli")
    dispatcher.attach()
