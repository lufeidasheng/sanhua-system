#!/usr/bin/env python3
"""
三花聚顶模块加载器 - 兼容事件总线接口完整版
支持安全检查、热重载、依赖管理、动作注册与事件订阅
保证事件总线接口调用统一使用 publish/subscribe/unsubscribe/shutdown
"""

import os
import sys
import importlib
import importlib.util
import logging
import time
import threading
import inspect
from pathlib import Path
from typing import (
    Callable, Optional, Dict, List, Any, Set, Tuple,
    TypeVar, Protocol, runtime_checkable
)
from dataclasses import dataclass, field
from threading import RLock
from watchdog.observers import Observer
from watchdog.events import FileSystemEvent, FileSystemEventHandler

T = TypeVar('T')
ModuleDict = Dict[str, 'ModuleMetadata']
DependencyGraph = Dict[str, List[str]]
SecurityRule = Tuple[str, str]  # (pattern, description)

@runtime_checkable
class IEventBus(Protocol):
    def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None: ...
    def subscribe(self, event_type: str, callback: Callable[[Any], None]) -> None: ...
    def unsubscribe(self, event_type: str, callback: Callable[[Any], None]) -> None: ...
    def shutdown(self) -> None: ...
    def is_initialized(self) -> bool: ...

@runtime_checkable
class IActionDispatcher(Protocol):
    def register_action(self, action_name: str, handler: Callable, *, module: str = None) -> None: ...
    def unregister_action(self, action_name: str) -> None: ...
    def clear_actions_by_module(self, module_name: str) -> None: ...
    def get_module_actions(self, module_name: str) -> Dict[str, Callable]: ...

@dataclass
class ModuleMetadata:
    module: Any
    file_path: Path
    version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    load_time: float = field(default_factory=time.time)
    is_package: bool = False
    initialized: bool = False
    actions: Dict[str, Callable] = field(default_factory=dict)
    event_handlers: Dict[str, Callable] = field(default_factory=dict)
    last_error: Optional[str] = None

class ModuleLoader:
    DEFAULT_SECURITY_RULES: List[SecurityRule] = [
        ("os.system(", "系统命令执行"),
        ("subprocess.run(", "子进程执行"),
        ("eval(", "代码求值"),
        ("exec(", "代码执行"),
        ("open(", "文件操作"),
        ("__import__(", "动态导入"),
        ("pickle.load", "不安全的反序列化"),
        ("marshal.load", "不安全的反序列化"),
        ("ctypes.", "底层系统调用"),
    ]

    def __init__(
        self,
        modules_dir: str,
        dispatcher: Optional[IActionDispatcher] = None,
        event_bus: Optional[IEventBus] = None,
        *,
        enable_hotreload: bool = True,
        security_check: Optional[bool] = None,
        max_file_size: int = 1024 * 1024,  # 1MB
        log_level: int = logging.INFO,
        hotreload_debounce: float = 0.5,
    ):
        self._setup_logging(log_level)
        self.logger = logging.getLogger("ModuleLoader")

        self.modules_dir = Path(modules_dir).resolve()
        self.dispatcher = dispatcher
        self.event_bus = event_bus
        self.enable_hotreload = enable_hotreload
        self.max_file_size = max_file_size
        self.hotreload_debounce = hotreload_debounce
        self._lock = RLock()
        self._shutdown_flag = False

        self.dependency_graph: DependencyGraph = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.loaded_modules: ModuleDict = {}
        self.security_policy: List[SecurityRule] = self.DEFAULT_SECURITY_RULES.copy()

        self.security_check = self._resolve_security_setting(security_check)
        self.observer: Optional[Observer] = None
        self._init_environment()

        if self.dispatcher is None:
            self.logger.warning("ModuleLoader 初始化时未传入 dispatcher，动作注册会失败！")

        self.logger.info(
            f"模块加载器初始化完成 (目录: {self.modules_dir}, "
            f"安全检查: {'开启' if self.security_check else '关闭'}, "
            f"热重载: {'开启' if enable_hotreload else '关闭'})"
        )

    def _setup_logging(self, log_level: int) -> None:
        logger = logging.getLogger("ModuleLoader")
        logger.setLevel(log_level)
        if not logger.hasHandlers():
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            logger.addHandler(ch)
            fh = logging.FileHandler("module_loader.log", encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)

    def _init_environment(self) -> None:
        try:
            self.modules_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"模块目录已初始化: {self.modules_dir}")
        except Exception as e:
            self.logger.error(f"初始化模块目录失败: {e}")
            raise RuntimeError(f"无法初始化模块目录: {e}")

    def load_all_modules(self) -> Tuple[int, int]:
        with self._lock:
            if not self.modules_dir.exists():
                self.logger.error(f"模块目录不存在: {self.modules_dir}")
                return 0, 0

            if self.enable_hotreload and self.observer is None:
                self._init_hotreload_monitor()

            module_files = self._find_module_files()
            results = []
            for file_path in module_files:
                module_name = self._path_to_module_name(file_path)
                success = self._load_module(module_name, file_path)
                results.append(success)

            success_count = sum(results)
            failure_count = len(results) - success_count
            self.logger.info(f"模块加载完成: 成功 {success_count}, 失败 {failure_count}")
            return success_count, failure_count

    def _load_module(self, module_name: str, file_path: Path) -> bool:
        with self._lock:
            if module_name in self.loaded_modules:
                return self.reload_module(module_name)

            if not self._run_security_checks(file_path):
                self.logger.error(f"安全检查失败: {module_name}")
                return False

            try:
                module = self._import_module(module_name, file_path)

                if not hasattr(module, 'initialize'):
                    raise AttributeError("模块缺少 initialize 方法")

                if not module.initialize():
                    raise RuntimeError("模块初始化返回 False")

                self._register_actions(module, module_name)
                self._register_event_handlers(module, module_name)

                meta = ModuleMetadata(
                    module=module,
                    file_path=file_path,
                    version=getattr(module, "__version__", "1.0.0"),
                    dependencies=getattr(module, "__depends__", []),
                    load_time=time.time(),
                    is_package=self._is_package(file_path),
                    initialized=True
                )
                self.loaded_modules[module_name] = meta
                self._update_dependency_graph(module_name)

                if cycles := self.check_circular_deps():
                    self.logger.error(f"检测到循环依赖: {cycles}")
                    self.unload_module(module_name, force=True)
                    return False

                self.logger.info(f"模块加载成功: {module_name} (版本: {meta.version})")
                return True

            except Exception as e:
                self.logger.error(f"加载模块失败: {module_name} - {str(e)}", exc_info=True)
                self._cleanup_failed_load(module_name)
                return False

    def reload_module(self, module_name: str) -> bool:
        with self._lock:
            if module_name not in self.loaded_modules:
                self.logger.warning(f"重载失败，模块未加载: {module_name}")
                return False

            dependents = self.reverse_dependencies.get(module_name, set())
            if dependents:
                self.logger.warning(f"重载模块 {module_name}，依赖它的模块: {', '.join(dependents)}")

            self.logger.info(f"开始重载模块: {module_name}")
            old_meta = self.loaded_modules[module_name]

            try:
                if not self._cleanup_module(module_name):
                    self.logger.warning(f"模块清理不彻底: {module_name}")

                spec = importlib.util.spec_from_file_location(
                    old_meta.module.__name__,
                    old_meta.file_path
                )
                if spec is None or spec.loader is None:
                    raise ImportError(f"无法创建模块规范: {module_name}")

                module = importlib.util.module_from_spec(spec)
                sys.modules[old_meta.module.__name__] = module
                spec.loader.exec_module(module)

                if not hasattr(module, 'initialize'):
                    raise AttributeError("模块缺少 initialize 方法")

                if not module.initialize():
                    raise RuntimeError("模块初始化返回 False")

                self._register_actions(module, module_name)
                self._register_event_handlers(module, module_name)

                self.loaded_modules[module_name] = ModuleMetadata(
                    module=module,
                    file_path=old_meta.file_path,
                    version=getattr(module, "__version__", old_meta.version),
                    dependencies=old_meta.dependencies.copy(),
                    load_time=time.time(),
                    is_package=old_meta.is_package,
                    initialized=True
                )

                self.logger.info(f"模块重载成功: {module_name}")
                return True

            except Exception as e:
                self.logger.error(f"重载模块失败: {module_name} - {str(e)}", exc_info=True)
                try:
                    importlib.reload(old_meta.module)
                except Exception:
                    pass
                return False

    def unload_module(self, module_name: str, force: bool = False) -> bool:
        with self._lock:
            if module_name not in self.loaded_modules:
                self.logger.warning(f"尝试卸载未加载模块: {module_name}")
                return False

            dependents = self.reverse_dependencies.get(module_name, set())
            if dependents and not force:
                self.logger.error(
                    f"无法卸载 {module_name}，依赖模块: {', '.join(dependents)}\n"
                    f"使用 force=True 强制卸载"
                )
                return False

            self.logger.info(f"卸载模块: {module_name}{' (强制)' if force else ''}")
            return self._cleanup_module(module_name)

    def shutdown(self) -> bool:
        with self._lock:
            self._shutdown_flag = True
            success = True

            if self.observer:
                try:
                    self.observer.stop()
                    self.observer.join()
                    self.logger.info("热重载监控已停止")
                except Exception as e:
                    self.logger.error(f"停止热重载监控失败: {e}")
                    success = False

            for mod_name in list(self.loaded_modules.keys()):
                if not self.unload_module(mod_name, force=True):
                    success = False

            self.logger.info("模块加载器已关闭")
            return success

    def _find_module_files(self) -> List[Path]:
        files = []
        for root, dirs, filenames in os.walk(self.modules_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in filenames:
                if f.endswith(".py") and not f.startswith("_"):
                    files.append(Path(root) / f)
        return files

    def _path_to_module_name(self, path: Path) -> str:
        try:
            rel_path = path.relative_to(self.modules_dir)
            return ".".join(rel_path.with_suffix("").parts)
        except ValueError as e:
            self.logger.error(f"路径转换失败: {path} - {e}")
            raise

    def _is_package(self, file_path: Path) -> bool:
        return file_path.name == "__init__.py"

    def _import_module(self, module_name: str, file_path: Path) -> Any:
        unique_name = f"{self.modules_dir.name}_{module_name}"
        if unique_name in sys.modules:
            del sys.modules[unique_name]

        spec = importlib.util.spec_from_file_location(unique_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建模块规范: {module_name}")

        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(file_path)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)
        return module

    def _run_security_checks(self, file_path: Path) -> bool:
        if not self.security_check:
            return True

        try:
            size = file_path.stat().st_size
            if size > self.max_file_size:
                self.logger.error(f"文件超出大小限制({size} > {self.max_file_size}): {file_path}")
                return False

            content = file_path.read_text(encoding="utf-8")
            for pattern, desc in self.security_policy:
                if pattern in content:
                    self.logger.error(f"检测到禁止模式 '{desc}': {file_path}")
                    return False
            return True
        except Exception as e:
            self.logger.error(f"安全检查异常: {file_path} - {e}")
            return False

    def _update_dependency_graph(self, module_name: str) -> None:
        deps = self.loaded_modules[module_name].dependencies
        self.dependency_graph[module_name] = deps.copy()

        for dep in deps:
            self.reverse_dependencies.setdefault(dep, set()).add(module_name)

    def check_circular_deps(self) -> List[List[str]]:
        visited = set()
        stack = set()
        cycles = []

        def dfs(node: str, path: List[str]) -> None:
            if node in stack:
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:] + [node])
                return
            if node in visited:
                return

            visited.add(node)
            stack.add(node)

            for neighbor in self.dependency_graph.get(node, []):
                dfs(neighbor, path + [neighbor])

            stack.remove(node)

        for mod in list(self.dependency_graph.keys()):
            dfs(mod, [mod])

        return cycles

    def _register_actions(self, module: Any, module_name: str) -> None:
        """
        自动适配 register_actions 函数签名，支持无参、单参、双参、带可变参数
        且强制检查 dispatcher 不为 None，防止调用 None 出错
        """
        if not hasattr(module, 'register_actions'):
            return

        if self.dispatcher is None:
            self.logger.error(f"模块 {module_name} 的 register_actions 无法执行，dispatcher为None")
            return

        try:
            reg_func = module.register_actions
            sig = inspect.signature(reg_func)
            params = sig.parameters

            args_to_pass = []
            if len(params) > 0:
                args_to_pass.append(self.dispatcher)
            if len(params) > 1:
                context = getattr(module, 'context', None)
                args_to_pass.append(context)

            reg_func(*args_to_pass[:len(params)])

            if (hasattr(self.dispatcher, 'get_module_actions') and
                callable(getattr(self.dispatcher, 'get_module_actions'))):
                actions = self.dispatcher.get_module_actions(module_name)
                if module_name in self.loaded_modules:
                    self.loaded_modules[module_name].actions = actions
                self.logger.debug(f"模块 {module_name} 注册动作: {list(actions.keys())}")

        except Exception as e:
            self.logger.error(f"注册动作失败: {module_name} - {e}", exc_info=True)

    def _register_event_handlers(self, module: Any, module_name: str) -> None:
        if not hasattr(module, 'event_handlers'):
            return

        handlers = getattr(module, 'event_handlers')
        if not isinstance(handlers, dict):
            self.logger.warning(f"模块 {module_name} 的 event_handlers 不是字典")
            return

        if self.event_bus is None:
            self.logger.warning("事件总线未配置，跳过事件注册")
            return

        # 统一用 publish/subscribe/unsubscribe/shutdown 的接口名检测
        required_methods = ['subscribe', 'publish', 'unsubscribe', 'shutdown']
        if not all(hasattr(self.event_bus, method) for method in required_methods):
            self.logger.warning("事件总线接口不完整，跳过事件注册")
            return

        registered = {}
        for event_type, handler in handlers.items():
            if not callable(handler):
                self.logger.warning(f"事件处理器不可调用: {event_type}")
                continue
            try:
                self.event_bus.subscribe(event_type, handler)
                registered[event_type] = handler
                self.logger.debug(f"注册事件处理器: {event_type}")
            except Exception as e:
                self.logger.error(f"注册事件失败: {event_type} - {e}")

        if module_name in self.loaded_modules:
            self.loaded_modules[module_name].event_handlers = registered

    def _cleanup_module(self, module_name: str) -> bool:
        if module_name not in self.loaded_modules:
            return False

        meta = self.loaded_modules[module_name]
        success = True

        if meta.event_handlers and self.event_bus is not None:
            for event_type, handler in meta.event_handlers.items():
                try:
                    self.event_bus.unsubscribe(event_type, handler)
                except Exception as e:
                    self.logger.warning(f"取消订阅失败: {event_type} - {e}")
                    success = False

        if hasattr(meta.module, 'cleanup'):
            try:
                cleanup_func = meta.module.cleanup
                if inspect.iscoroutinefunction(cleanup_func):
                    import asyncio
                    asyncio.run(cleanup_func())
                else:
                    if cleanup_func() is False:
                        self.logger.warning(f"模块 cleanup 返回 False: {module_name}")
                        success = False
            except Exception as e:
                self.logger.error(f"模块清理异常: {module_name} - {e}")
                success = False

        if self.dispatcher is not None:
            try:
                self.dispatcher.clear_actions_by_module(module_name)
            except Exception as e:
                self.logger.error(f"清理动作失败: {module_name} - {e}")
                success = False

        try:
            if meta.module.__name__ in sys.modules:
                del sys.modules[meta.module.__name__]
            del self.loaded_modules[module_name]
            self.dependency_graph.pop(module_name, None)
            for dep in self.reverse_dependencies:
                self.reverse_dependencies[dep].discard(module_name)
        except Exception as e:
            self.logger.error(f"移除模块失败: {module_name} - {e}")
            success = False

        return success

    def _cleanup_failed_load(self, module_name: str) -> None:
        if module_name in sys.modules:
            del sys.modules[module_name]
        if module_name in self.loaded_modules:
            del self.loaded_modules[module_name]
        self.dependency_graph.pop(module_name, None)
        for dep in self.reverse_dependencies:
            self.reverse_dependencies[dep].discard(module_name)

    def _init_hotreload_monitor(self) -> None:
        class ModuleChangeHandler(FileSystemEventHandler):
            def __init__(self, loader: 'ModuleLoader'):
                self.loader = loader
                self._timers: Dict[str, threading.Timer] = {}
                self._last_modified: Dict[str, float] = {}

            def on_modified(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return

                path = Path(event.src_path)
                if path.suffix != '.py' or path.name.startswith('_'):
                    return

                try:
                    module_name = self.loader._path_to_module_name(path)
                except ValueError:
                    return

                now = time.time()
                last = self._last_modified.get(module_name, 0)
                if now - last < self.loader.hotreload_debounce:
                    return
                self._last_modified[module_name] = now

                if module_name in self._timers:
                    self._timers[module_name].cancel()

                timer = threading.Timer(
                    self.loader.hotreload_debounce,
                    self._trigger_reload,
                    args=[module_name]
                )
                self._timers[module_name] = timer
                timer.start()

            def _trigger_reload(self, module_name: str) -> None:
                self.loader.logger.info(f"检测到文件变更，重载模块: {module_name}")
                self.loader.reload_module(module_name)
                if module_name in self._timers:
                    del self._timers[module_name]

        self.observer = Observer()
        handler = ModuleChangeHandler(self)
        self.observer.schedule(handler, str(self.modules_dir), recursive=True)
        self.observer.start()
        self.logger.info(f"热重载监控已启动 (防抖时间: {self.hotreload_debounce}s)")

    def _resolve_security_setting(self, setting: Optional[bool]) -> bool:
        if setting is not None:
            return setting
        env_val = os.getenv('MODULE_LOADER_SECURITY_CHECK', 'true').lower()
        return env_val in ('true', '1', 'yes', 'on')

    def add_security_rule(self, pattern: str, description: str) -> None:
        self.security_policy.append((pattern, description))
        self.logger.info(f"添加安全规则: {description}")

    def list_modules(self, loaded_only: bool = True) -> List[str]:
        with self._lock:
            if loaded_only:
                return list(self.loaded_modules.keys())
            else:
                modules = set()
                for root, _, files in os.walk(self.modules_dir):
                    for file in files:
                        if file.endswith(".py") and not file.startswith("_"):
                            try:
                                path = Path(root) / file
                                modules.add(self._path_to_module_name(path))
                            except Exception:
                                continue
                return sorted(modules)

    def get_module(self, module_name: str) -> Optional[Any]:
        with self._lock:
            meta = self.loaded_modules.get(module_name)
            return meta.module if meta else None

    def get_module_metadata(self, module_name: str) -> Optional[ModuleMetadata]:
        with self._lock:
            return self.loaded_modules.get(module_name)

    def is_module_loaded(self, module_name: str) -> bool:
        with self._lock:
            return module_name in self.loaded_modules

    def get_dependents(self, module_name: str) -> Set[str]:
        with self._lock:
            return self.reverse_dependencies.get(module_name, set()).copy()
