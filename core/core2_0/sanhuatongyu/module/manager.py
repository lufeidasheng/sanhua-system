import os
import sys
import json
import time
import types
import inspect
import importlib
import importlib.util
from collections import deque
from typing import Dict, List, Type, Any, Optional, Tuple

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .meta import ModuleMeta
from .base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger

logger = get_logger("module_manager")


# ===== 脚手架兼容层 =====
class LegacyModuleManager:
    """兼容脚手架 register_actions/initialize/cleanup 单文件包式模块"""

    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.module_map: Dict[str, Any] = {}
        self.load_order: List[str] = []
        self.logger = get_logger("legacy_loader")

    def load_module(self, module_name: str, dependencies: Optional[List[str]] = None) -> bool:
        try:
            if module_name in self.module_map:
                return self.reload_module(module_name)

            module = importlib.import_module(module_name)

            # 注册动作
            if hasattr(module, "register_actions"):
                module.register_actions(self.dispatcher)

            # 初始化
            if hasattr(module, "initialize"):
                ok = module.initialize()
                if ok is False:
                    return False

            self.module_map[module_name] = module
            self.load_order.append(module_name)
            self.logger.info("legacy_module_loaded", extra={"module": module_name})
            return True

        except Exception as e:
            self.logger.error("legacy_module_load_failed", extra={"module": module_name, "error": str(e)})
            return False

    def reload_module(self, module_name: str) -> bool:
        try:
            if module_name not in self.module_map:
                return self.load_module(module_name)

            module = importlib.reload(self.module_map[module_name])

            if hasattr(module, "register_actions"):
                module.register_actions(self.dispatcher)

            if hasattr(module, "initialize"):
                module.initialize()

            self.module_map[module_name] = module
            self.logger.info("legacy_module_reloaded", extra={"module": module_name})
            return True

        except Exception as e:
            self.logger.error("legacy_module_reload_failed", extra={"module": module_name, "error": str(e)})
            return False

    def unload_module(self, module_name: str) -> bool:
        try:
            if module_name not in self.module_map:
                return False

            module = self.module_map[module_name]

            if hasattr(self.dispatcher, "clear_actions_by_module"):
                self.dispatcher.clear_actions_by_module(module_name)

            if hasattr(module, "cleanup"):
                module.cleanup()

            del self.module_map[module_name]
            if module_name in self.load_order:
                self.load_order.remove(module_name)

            self.logger.info("legacy_module_unloaded", extra={"module": module_name})
            return True

        except Exception as e:
            self.logger.error("legacy_module_unload_failed", extra={"module": module_name, "error": str(e)})
            return False

    def list_modules(self):
        return list(self.module_map.keys())


# ========== 主 manifest+BaseModule 加载体系 ==========
class ModuleChangeHandler(FileSystemEventHandler):
    def __init__(self, module_manager: "ModuleManager"):
        self.module_manager = module_manager
        self.logger = get_logger("hotswap")

    def on_modified(self, event):
        if event.is_directory:
            return
        if ("manifest.json" in event.src_path) or ("module.py" in event.src_path):
            module_name = os.path.basename(os.path.dirname(event.src_path))
            self.logger.info("module_file_changed", extra={"module": module_name})
            self.module_manager.reload_module(module_name)

    def on_created(self, event):
        if event.is_directory:
            module_dir = event.src_path
            manifest_path = os.path.join(module_dir, "manifest.json")
            if os.path.exists(manifest_path):
                module_name = os.path.basename(module_dir)
                self.logger.info("new_module_detected", extra={"module": module_name})
                self.module_manager.load_single_module(module_name)

    def on_deleted(self, event):
        if event.is_directory:
            module_name = os.path.basename(event.src_path)
            self.logger.info("module_removed", extra={"module": module_name})
            self.module_manager.unload_module(module_name)


class ModuleManager:
    """
    三花聚顶 · 融合型模块加载器
    - 支持 manifest + BaseModule（主体系）
    - 支持 register_actions/initialize/cleanup（legacy 兼容）
    - 【关键增强】按 modules.<name>.module 的可导入名加载，兼容 macOS spawn/pickling
    - 【关键增强】BaseModule 子类找不到时自动降级到 legacy，而不是直接判死刑
    """

    def __init__(self, modules_dir: str, context: "SystemContext"):
        self.modules_dir = modules_dir
        self.context = context
        self.logger = logger

        # 确保项目根目录可导入 modules.<name> 包
        # modules_dir = /xxx/聚核助手2.0/modules
        project_root = os.path.abspath(os.path.join(modules_dir, os.pardir))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        self.modules: Dict[str, ModuleMeta] = {}
        self.loaded_modules: Dict[str, BaseModule] = {}

        self.hotswap_handler = ModuleChangeHandler(self)
        self.observer = None
        self._observer_needs_rebuild = False
        self._modules_started = False
        self._ensure_observer()

        # legacy 兼容层
        self.legacy_loader = LegacyModuleManager(context.action_dispatcher)

    def _ensure_observer(self):
        if self.observer is not None and not self._observer_needs_rebuild:
            return self.observer

        self.observer = Observer()
        self._observer_needs_rebuild = False
        try:
            self.observer.schedule(self.hotswap_handler, self.modules_dir, recursive=True)
        except Exception as e:
            self.logger.error("observer_schedule_failed", extra={"error": str(e)})
        return self.observer

    # === 兼容层 API ===
    def load_legacy_module(self, module_name: str, dependencies: list = None):
        return self.legacy_loader.load_module(module_name, dependencies)

    def unload_legacy_module(self, module_name: str):
        return self.legacy_loader.unload_module(module_name)

    def reload_legacy_module(self, module_name: str):
        return self.legacy_loader.reload_module(module_name)

    def list_legacy_modules(self):
        return self.legacy_loader.list_modules()

    # === manifest+BaseModule 主流体系 ===
    def load_modules_metadata(self) -> None:
        self.logger.info("scanning_modules", extra={"path": self.modules_dir})
        for mod_name in os.listdir(self.modules_dir):
            mod_path = os.path.join(self.modules_dir, mod_name)
            manifest_path = os.path.join(mod_path, "manifest.json")
            if not os.path.isdir(mod_path) or not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                if "name" not in manifest or manifest["name"] != mod_name:
                    self.logger.error(
                        "name_mismatch",
                        extra={"module": mod_name, "manifest_name": manifest.get("name")},
                    )
                    continue
                meta = ModuleMeta(mod_name, mod_path, manifest)
                self.modules[mod_name] = meta
                self.logger.debug(
                    "module_metadata_loaded",
                    extra={"module": mod_name, "version": meta.version, "fingerprint": meta.fingerprint},
                )
            except Exception as e:
                self.logger.error("metadata_failed", extra={"module": mod_name, "error": str(e)})

    def _resolve_dependencies(self) -> List[str]:
        graph = {name: set(meta.dependencies) for name, meta in self.modules.items()}
        in_degree = {name: 0 for name in self.modules}
        for node, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[node] += 1
        queue = deque([name for name, degree in in_degree.items() if degree == 0])
        load_order = []
        while queue:
            node = queue.popleft()
            load_order.append(node)
            for dependent, deps in graph.items():
                if node in deps:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)
        if len(load_order) != len(self.modules):
            cyclic = set(self.modules.keys()) - set(load_order)
            self.logger.error("cyclic_dependency", extra={"modules": ",".join(cyclic)})
            raise RuntimeError(f"cyclic_dependency: {','.join(cyclic)}")
        return load_order

    # -------------------------
    # 关键：确保 modules.<name> 作为可导入包存在（相对导入、spawn pickling 都需要）
    # -------------------------
    def _ensure_package_stub(self, pkg_name: str, pkg_path: str) -> None:
        """
        为本地模块目录创建一个“包桩”，确保：
        - import modules.xxx 能成功
        - module.py 内部的相对导入（from .xxx import ...）不崩
        - multiprocessing spawn 需要的可导入路径存在
        """
        if pkg_name in sys.modules:
            return

        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [pkg_path]  # type: ignore
        pkg.__file__ = os.path.join(pkg_path, "__init__.py")
        sys.modules[pkg_name] = pkg

    def _import_module_from_file(self, import_name: str, file_path: str, pkg_dir: str) -> Any:
        """
        用稳定 import_name 从 file_path 导入，并写入 sys.modules，使其可被 spawn 复用。
        """
        spec = importlib.util.spec_from_file_location(import_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"spec_create_failed: {import_name} -> {file_path}")

        module = importlib.util.module_from_spec(spec)
        # 重要：提前注册，避免递归导入/相对导入时找不到
        sys.modules[import_name] = module
        # 让相对导入基于包进行解析
        module.__package__ = import_name.rsplit(".", 1)[0]

        spec.loader.exec_module(module)
        return module

    def _load_module_class_by_entry_class(self, mod_meta: ModuleMeta) -> Optional[Type[BaseModule]]:
        """
        优先用 manifest.entry_class 精确定位 BaseModule 子类。
        期待 entry_class 类似：
          modules.audio_capture.module.AudioCaptureModule
        """
        entry_class = None
        try:
            entry_class = getattr(mod_meta, "entry_class", None) or (
                mod_meta.manifest.get("entry_class") if hasattr(mod_meta, "manifest") else None
            )
        except Exception:
            entry_class = None

        if not entry_class or not isinstance(entry_class, str):
            return None

        entry_class = entry_class.strip()
        if not entry_class:
            return None

        try:
            mod_path, cls_name = entry_class.rsplit(".", 1)
            py_mod = importlib.import_module(mod_path)
            cls = getattr(py_mod, cls_name, None)
            if inspect.isclass(cls) and issubclass(cls, BaseModule) and cls is not BaseModule:
                return cls
            return None
        except Exception as e:
            self.logger.debug(
                "entry_class_import_failed",
                extra={"module": mod_meta.name, "entry_class": entry_class, "error": str(e)},
            )
            return None

    def _scan_module_for_basemodule(self, py_module: Any, mod_name: str) -> Optional[Type[BaseModule]]:
        """
        扫描 module.py 中的 BaseModule 子类。
        """
        found: List[Type[BaseModule]] = []
        for _, obj in inspect.getmembers(py_module):
            if inspect.isclass(obj) and issubclass(obj, BaseModule) and obj is not BaseModule:
                found.append(obj)

        if not found:
            return None
        if len(found) == 1:
            return found[0]

        # 多个子类：优先名字像 *Module 的
        found.sort(key=lambda c: (0 if c.__name__.endswith("Module") else 1, c.__name__))
        self.logger.warning(
            "multiple_basemodule_found",
            extra={"module": mod_name, "candidates": [c.__name__ for c in found]},
        )
        return found[0]

    # === SANHUA_MODULE_CLASS_RESOLUTION_PATCH_V1 START ===
    def _sanhua_camelize_module_name(self, name):
        parts = [p for p in str(name).replace("-", "_").split("_") if p]
        return "".join(p[:1].upper() + p[1:] for p in parts)

    def _sanhua_pick_best_module_class(self, mod_meta, candidates):
        if not candidates:
            return None

        entry_class = getattr(mod_meta, "entry_class", "") or ""
        preferred_name = entry_class.rsplit(".", 1)[-1] if "." in entry_class else entry_class
        module_name = getattr(mod_meta, "name", "") or ""

        expected_names = []
        if preferred_name:
            expected_names.append(preferred_name)

        camel = self._sanhua_camelize_module_name(module_name) if module_name else ""
        if camel:
            expected_names.extend([
                f"Official{camel}Module",
                f"{camel}Module",
                camel,
            ])

        seen = set()
        ordered_names = []
        for name in expected_names:
            if name and name not in seen:
                seen.add(name)
                ordered_names.append(name)

        by_name = {cls.__name__: cls for cls in candidates}

        for name in ordered_names:
            cls = by_name.get(name)
            if cls is not None:
                return cls

        for cls in candidates:
            if cls.__name__.startswith("Official"):
                return cls

        for cls in candidates:
            try:
                if not inspect.isabstract(cls):
                    return cls
            except Exception:
                return cls

        return candidates[0]
    # === SANHUA_MODULE_CLASS_RESOLUTION_PATCH_V1 END ===

    def _load_module_class(self, mod_meta):
        from core.core2_0.sanhuatongyu.module.base import BaseModule

        entry_class = getattr(mod_meta, "entry_class", "") or ""
        module_name = getattr(mod_meta, "name", "") or ""

        explicit_module_path = entry_class.rsplit(".", 1)[0] if "." in entry_class else ""
        explicit_class_name = entry_class.rsplit(".", 1)[-1] if "." in entry_class else entry_class

        candidate_module_paths = []
        for path in (
            explicit_module_path,
            f"modules.{module_name}.module" if module_name else "",
            f"modules.{module_name}" if module_name else "",
        ):
            if path and path not in candidate_module_paths:
                candidate_module_paths.append(path)

        module_obj = None
        import_errors = []

        for path in candidate_module_paths:
            try:
                module_obj = importlib.import_module(path)
                break
            except Exception as e:
                import_errors.append(f"{path}: {e}")

        if module_obj is None:
            raise ImportError(
                f"模块导入失败: {module_name} | tried={candidate_module_paths} | "
                f"errors={' | '.join(import_errors)}"
            )

        if explicit_class_name:
            explicit_cls = getattr(module_obj, explicit_class_name, None)
            if inspect.isclass(explicit_cls):
                try:
                    if issubclass(explicit_cls, BaseModule) and explicit_cls is not BaseModule:
                        return explicit_cls
                except Exception:
                    pass

        entry_obj = getattr(module_obj, "entry", None)
        if inspect.isclass(entry_obj):
            try:
                if issubclass(entry_obj, BaseModule) and entry_obj is not BaseModule:
                    return entry_obj
            except Exception:
                pass

        candidates = []
        for _, obj in vars(module_obj).items():
            if not inspect.isclass(obj):
                continue
            if obj is BaseModule:
                continue
            try:
                if not issubclass(obj, BaseModule):
                    continue
            except Exception:
                continue

            if getattr(obj, "__module__", None) != module_obj.__name__:
                continue

            candidates.append(obj)

        if not candidates:
            raise TypeError(f"未找到BaseModule子类: {module_name}")

        if len(candidates) == 1:
            return candidates[0]

        chosen = self._sanhua_pick_best_module_class(mod_meta, candidates)

        _logger = getattr(self, "logger", None)
        if _logger is not None:
            try:
                _logger.debug(
                    "multiple_basemodule_found: module=%s candidates=%s selected=%s",
                    module_name,
                    [cls.__name__ for cls in candidates],
                    getattr(chosen, "__name__", str(chosen)),
                )
            except Exception:
                pass

        return chosen

    def _initialize_module(self, mod_meta: ModuleMeta) -> BaseModule:
        module_class = self._load_module_class(mod_meta)
        instance = module_class(mod_meta, self.context)

        # preload 阶段就要允许失败不影响全局（企业容错）
        try:
            if mod_meta.name == "music_module":
                self.logger.info("music_module_preload_start")
            instance.preload()
            if mod_meta.name == "music_module":
                self.logger.info("music_module_preload_ok")
        except Exception as e:
            if mod_meta.name == "music_module":
                self.logger.error("music_module_preload_failed", extra={"error": str(e)})
            self.logger.error("module_preload_failed", extra={"module": mod_meta.name, "error": str(e)})

        if mod_meta.name in self.context.config_manager.module_configs:
            instance.config = self.context.config_manager.module_configs[mod_meta.name]

        if hasattr(instance, "get_provided_services"):
            try:
                services = instance.get_provided_services() or {}
                for service_name, service_obj in services.items():
                    self.context.register_service(service_name, service_obj)
                    self.logger.info("service_registered", extra={"service": service_name, "module": mod_meta.name})
            except Exception as e:
                self.logger.error("service_register_failed", extra={"module": mod_meta.name, "error": str(e)})

        return instance

    def _try_load_as_legacy(self, module_name: str) -> bool:
        """
        当 BaseModule 体系失败时，降级使用 legacy 兼容加载：
        优先尝试 modules.<name>.module，其次 modules.<name>
        """
        candidates = [f"modules.{module_name}.module", f"modules.{module_name}"]
        for dotted in candidates:
            ok = self.legacy_loader.load_module(dotted)
            if ok:
                self.logger.warning(
                    "module_loaded_as_legacy",
                    extra={"module": module_name, "import": dotted},
                )
                return True
        return False

    def load_single_module(self, module_name: str) -> bool:
        if module_name in self.loaded_modules:
            self.logger.warning("module_already_loaded", extra={"module": module_name})
            return False

        if module_name not in self.modules:
            self.logger.error("module_meta_missing", extra={"module": module_name})
            return False

        try:
            if module_name == "music_module":
                self.logger.info("music_module_load_single_start")
            meta = self.modules[module_name]
            instance = self._initialize_module(meta)
            self.loaded_modules[module_name] = instance

            if module_name == "music_module":
                self.logger.info("music_module_setup_start")
            instance.setup()
            if module_name == "music_module":
                self.logger.info("music_module_setup_ok")

            if self.context.system_running:
                instance.start()
                instance.post_start()

            self.logger.info("module_loaded_success", extra={"module": module_name})
            if module_name == "music_module":
                self.logger.info("music_module_loaded_success")
            return True

        except TypeError as e:
            # 典型：未找到 BaseModule 子类 -> 自动降级 legacy
            self.logger.error("module_load_failed", extra={"module": module_name, "error": str(e)})
            legacy_ok = self._try_load_as_legacy(module_name)
            if module_name == "music_module":
                self.logger.error("music_module_load_failed_type", extra={"error": str(e), "legacy_ok": legacy_ok})
            return legacy_ok

        except Exception as e:
            self.logger.error("module_load_failed", extra={"module": module_name, "error": str(e)})
            if module_name == "music_module":
                self.logger.error("music_module_load_failed", extra={"error": str(e)})
            return False

    def unload_module(self, module_name: str) -> bool:
        # 先尝试卸载 BaseModule
        if module_name in self.loaded_modules:
            try:
                module = self.loaded_modules[module_name]
                module.stop()
                module.on_shutdown()

                if hasattr(module, "get_provided_services"):
                    try:
                        for service_name in (module.get_provided_services() or {}).keys():
                            if service_name in self.context.services:
                                del self.context.services[service_name]
                    except Exception:
                        pass

                del self.loaded_modules[module_name]
                self.logger.info("module_unloaded", extra={"module": module_name})
                return True

            except Exception as e:
                self.logger.error("unload_failed", extra={"module": module_name, "error": str(e)})
                return False

        # 再尝试卸载 legacy（两种可能的 dotted name）
        unloaded = False
        for dotted in [f"modules.{module_name}.module", f"modules.{module_name}"]:
            if dotted in self.legacy_loader.module_map:
                unloaded = self.legacy_loader.unload_module(dotted) or unloaded

        if unloaded:
            self.logger.info("module_unloaded_legacy", extra={"module": module_name})
            return True

        self.logger.warning("module_not_loaded", extra={"module": module_name})
        return False

    def reload_module(self, module_name: str) -> bool:
        self.logger.info("reloading_module", extra={"module": module_name})
        if self.unload_module(module_name):
            mod_path = os.path.join(self.modules_dir, module_name)
            manifest_path = os.path.join(mod_path, "manifest.json")
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self.modules[module_name] = ModuleMeta(module_name, mod_path, manifest)
            except Exception as e:
                self.logger.error("reload_metadata_failed", extra={"module": module_name, "error": str(e)})
            return self.load_single_module(module_name)
        return False

    def restart_module(self, module_name: str) -> bool:
        if module_name not in self.loaded_modules:
            self.logger.warning("module_not_loaded", extra={"module": module_name})
            return False
        try:
            module = self.loaded_modules[module_name]
            module.stop()
            module.start()
            module.post_start()
            module.health_status = "OK"
            module.failure_count = 0
            self.logger.info("module_restarted", extra={"module": module_name})
            return True
        except Exception as e:
            self.logger.error("restart_failed", extra={"module": module_name, "error": str(e)})
            return False

    def load_modules(self, entry_point: str) -> None:
        self.logger.info("loading_modules", extra={"entry": entry_point})
        to_load = []
        for name, meta in self.modules.items():
            if not meta.enabled:
                if name == "music_module":
                    self.logger.info("music_module_filtered", extra={"reason": "disabled"})
                continue
            if meta.debug_only and not self.context.dev_mode:
                if name == "music_module":
                    self.logger.info("music_module_filtered", extra={"reason": "debug_only"})
                continue
            if meta.visibility in ["core", "service"] or entry_point in meta.entry_points:
                to_load.append(name)
            else:
                if name == "music_module":
                    self.logger.info("music_module_filtered", extra={"reason": "entry_point_mismatch"})

        try:
            load_order = self._resolve_dependencies()
            to_load = [name for name in load_order if name in to_load]
        except Exception as e:
            self.logger.error("dependency_resolve_failed", extra={"error": str(e)})
            to_load = sorted(to_load)

        if "music_module" in to_load:
            self.logger.info("music_module_in_to_load", extra={"entry": entry_point})
        else:
            self.logger.info("music_module_not_in_to_load", extra={"entry": entry_point})

        for mod_name in to_load:
            self.load_single_module(mod_name)

    def start_modules(self) -> None:
        if self._modules_started:
            self.logger.info("modules_already_started")
            return

        self.logger.info("starting_modules")
        self._modules_started = True

        # 复制 keys，避免 start 内部触发热加载导致 dict 变化
        for mod_name in list(self.loaded_modules.keys()):
            module = self.loaded_modules.get(mod_name)
            if not module:
                continue
            try:
                module.start()
            except Exception as e:
                self.logger.error("start_failed", extra={"module": mod_name, "error": str(e)})

        for mod_name in list(self.loaded_modules.keys()):
            module = self.loaded_modules.get(mod_name)
            if not module:
                continue
            try:
                module.post_start()
            except Exception as e:
                self.logger.error("post_start_failed", extra={"module": mod_name, "error": str(e)})

        try:
            observer = self._ensure_observer()
            if observer is not None and not observer.is_alive():
                observer.start()
        except Exception as e:
            self.logger.error("observer_start_failed", extra={"error": str(e)})

    def stop_modules(self) -> None:
        if not self._modules_started:
            self.logger.info("modules_already_stopped")
            return

        self.logger.info("stopping_modules")
        try:
            if self.observer is not None and self.observer.is_alive():
                self.observer.stop()
                self.observer.join()
                self._observer_needs_rebuild = True
        except Exception as e:
            self.logger.error("observer_stop_failed", extra={"error": str(e)})

        for mod_name in reversed(list(self.loaded_modules.keys())):
            try:
                self.loaded_modules[mod_name].stop()
            except Exception as e:
                self.logger.error("stop_failed", extra={"module": mod_name, "error": str(e)})

        for module in reversed(list(self.loaded_modules.values())):
            try:
                module.on_shutdown()
            except Exception as e:
                name = getattr(getattr(module, "meta", None), "name", "unknown")
                self.logger.error("shutdown_failed", extra={"module": name, "error": str(e)})

        # legacy 停止（仅 cleanup）
        for dotted in reversed(self.legacy_loader.load_order):
            try:
                self.legacy_loader.unload_module(dotted)
            except Exception:
                pass

        self._modules_started = False

    def health_check(self) -> Dict[str, Any]:
        report = {
            "status": "OK",
            "timestamp": time.time(),
            "modules": {},
            "legacy_modules": {},
            "system_uptime": time.time() - self.context.start_time,
        }

        for name, module in self.loaded_modules.items():
            try:
                module_report = module.health_check()
                meta = self.modules.get(name)
                if meta:
                    module_report["fingerprint"] = meta.fingerprint
                    module_report["version"] = meta.version
                report["modules"][name] = module_report
                status = module_report.get("status")
                if not status:
                    status = module_report.get("health", "OK")
                    module_report["status"] = status
                status_norm = str(status or "UNKNOWN").strip().upper()
                status_map = {
                    "正常": "OK",
                    "就绪": "READY",
                    "停止": "STOPPED",
                    "降级": "DEGRADED",
                    "失败": "FAILED",
                    "错误": "ERROR",
                }
                status_norm = status_map.get(status_norm, status_norm)
                module_report["status"] = status_norm
                if status_norm not in ("OK", "STOPPED"):
                    report["status"] = "WARNING"
            except Exception as e:
                report["modules"][name] = {"status": "ERROR", "error": str(e)}
                report["status"] = "CRITICAL"

        for name in self.legacy_loader.list_modules():
            report["legacy_modules"][name] = {"status": "UNKNOWN"}

        return report

    def _module_name_candidates(self, module_name: str) -> List[str]:
        """为兼容不同调用方风格，生成可匹配的模块名候选。"""
        raw = (module_name or "").strip()
        if not raw:
            return []

        candidates: List[str] = []

        def _add(name: str) -> None:
            if name and name not in candidates:
                candidates.append(name)

        _add(raw)

        if raw.endswith(".module"):
            _add(raw[: -len(".module")])

        parts = raw.split(".")
        if parts:
            _add(parts[-1])
            if len(parts) >= 2 and parts[-1] == "module":
                _add(parts[-2])

        short_name = parts[-1] if parts else raw
        if short_name and short_name != "module":
            _add(f"modules.{short_name}")
            _add(f"modules.{short_name}.module")

        return candidates

    def get_module(self, module_name: str):
        """
        兼容获取已加载模块实例。

        支持以下调用形式：
        - 短名：code_reader
        - 包路径：modules.code_reader
        - module.py 路径：modules.code_reader.module
        - 其他 dotted name：自动回退到末段 / 倒数第二段匹配
        """
        loaded_modules = getattr(self, "loaded_modules", {}) or {}

        legacy_loader = getattr(self, "legacy_loader", None)
        legacy_module_map = getattr(legacy_loader, "module_map", {}) if legacy_loader else {}

        for candidate in self._module_name_candidates(module_name):
            if candidate in loaded_modules:
                return loaded_modules[candidate]

            if candidate in legacy_module_map:
                return legacy_module_map[candidate]

        return None

    def list_all_modules(self):
        """返回所有已加载模块（原生+legacy）"""
        return list(self.loaded_modules.keys()) + self.legacy_loader.list_modules()
