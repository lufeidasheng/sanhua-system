from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class CodeReaderModule:
    """
    三花聚顶 code_reader 正式最小可用版（安全读取版）
    目标：
    1. 提供 code_reader.exists / code_reader.read_file / code_reader.list_dir
    2. register_actions(dispatcher) 可直接被 bootstrap 调用
    3. 不做写入，只做安全读取
    """

    name = "code_reader"
    version = "2.0.0"
    title = "Code Reader Module"

    def __init__(self, *args, **kwargs):
        self.started = False
        self.project_root = Path.cwd()

    def start(self) -> Dict[str, Any]:
        self.started = True
        return {
            "ok": True,
            "module": self.name,
            "status": "started",
        }

    def stop(self) -> Dict[str, Any]:
        self.started = False
        return {
            "ok": True,
            "module": self.name,
            "status": "stopped",
        }

    def _resolve_path(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Path:
        path_value = None

        if "path" in kwargs and kwargs["path"]:
            path_value = kwargs["path"]
        elif context and context.get("path"):
            path_value = context.get("path")
        else:
            path_value = "config/global.yaml"

        p = Path(str(path_value))
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    def action_exists(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "exists",
            "timestamp": int(time.time()),
            "path": str(p),
            "exists": p.exists(),
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "started": self.started,
        }

    def action_read_file(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        max_chars = kwargs.get("max_chars")
        if max_chars is None and context:
            max_chars = context.get("max_chars")
        try:
            max_chars = int(max_chars or 4000)
        except Exception:
            max_chars = 4000

        if not p.exists():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "file_not_found",
            }

        if not p.is_file():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "not_a_file",
            }

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": str(e),
            }

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "read_file",
            "timestamp": int(time.time()),
            "path": str(p),
            "exists": True,
            "truncated": truncated,
            "max_chars": max_chars,
            "content": text,
            "started": self.started,
        }

    def action_list_dir(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        limit = kwargs.get("limit")
        if limit is None and context:
            limit = context.get("limit")
        try:
            limit = int(limit or 50)
        except Exception:
            limit = 50

        if not p.exists():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "path_not_found",
            }

        if not p.is_dir():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "not_a_dir",
            }

        try:
            entries = []
            for child in sorted(p.iterdir(), key=lambda x: x.name)[:limit]:
                entries.append({
                    "name": child.name,
                    "is_file": child.is_file(),
                    "is_dir": child.is_dir(),
                })
        except Exception as e:
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": str(e),
            }

        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "list_dir",
            "timestamp": int(time.time()),
            "path": str(p),
            "count": len(entries),
            "entries": entries,
            "limit": limit,
            "started": self.started,
        }


def get_module_instance(*args, **kwargs) -> CodeReaderModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = CodeReaderModule(*args, **kwargs)
    return _MODULE_SINGLETON


def _safe_unregister(dispatcher: Any, action_name: str) -> None:
    try:
        existing = dispatcher.get_action(action_name) if hasattr(dispatcher, "get_action") else None
    except Exception:
        existing = None

    if existing is not None and hasattr(dispatcher, "unregister_action"):
        try:
            dispatcher.unregister_action(action_name)
        except Exception:
            pass


def _safe_register(dispatcher: Any, action_name: str, func: Any) -> None:
    _safe_unregister(dispatcher, action_name)
    dispatcher.register_action(action_name, func)


def _safe_register_aliases(dispatcher: Any, action_name: str, aliases: list[str]) -> None:
    if not aliases:
        return

    if hasattr(dispatcher, "register_aliases"):
        try:
            dispatcher.register_aliases(action_name, aliases)
            return
        except TypeError:
            pass
        except Exception:
            pass

    if hasattr(dispatcher, "register_alias"):
        for alias in aliases:
            try:
                dispatcher.register_alias(alias, action_name)
                continue
            except TypeError:
                pass
            except Exception:
                pass

            try:
                dispatcher.register_alias(action_name, alias)
            except Exception:
                pass


def register_actions(dispatcher: Any) -> Dict[str, Any]:
    module = get_module_instance()

    _safe_register(dispatcher, "code_reader.exists", module.action_exists)
    _safe_register(dispatcher, "code_reader.read_file", module.action_read_file)
    _safe_register(dispatcher, "code_reader.list_dir", module.action_list_dir)

    _safe_register_aliases(
        dispatcher,
        "code_reader.exists",
        [
            "文件是否存在",
            "检查文件是否存在",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "code_reader.read_file",
        [
            "读取文件",
            "查看文件内容",
            "读取配置文件",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "code_reader.list_dir",
        [
            "列出目录",
            "查看目录内容",
        ],
    )

    log.info("code_reader 动作注册完成: code_reader.exists / code_reader.read_file / code_reader.list_dir")
    return {
        "ok": True,
        "module": "code_reader",
        "actions": [
            "code_reader.exists",
            "code_reader.read_file",
            "code_reader.list_dir",
        ],
    }


def entry(*args, **kwargs) -> CodeReaderModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "CodeReaderModule",
    "get_module_instance",
    "register_actions",
    "entry",
]

# === SANHUA_OFFICIAL_WRAPPER_START ===
try:
    from core.core2_0.sanhuatongyu.module.base import BaseModule as _SanhuaBaseModule
except Exception:
    _SanhuaBaseModule = object


def _sanhua_safe_call(_fn, *args, **kwargs):
    if not callable(_fn):
        return None

    last_error = None

    trials = [
        lambda: _fn(*args, **kwargs),
        lambda: _fn(*args),
        lambda: _fn(),
    ]
    for call in trials:
        try:
            return call()
        except TypeError as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return None


class OfficialCodeReaderModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for legacy module: code_reader
    """

    def __init__(self, *args, **kwargs):
        context = kwargs.pop("context", None) if "context" in kwargs else None
        self.context = context
        self.dispatcher = kwargs.get("dispatcher")
        self.started = False

        try:
            super().__init__(*args, **kwargs)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass

        if self.context is None:
            self.context = context

    def _resolve_dispatcher(self, context=None):
        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            obj = getattr(self, name, None)
            if obj is not None:
                return obj

        if isinstance(context, dict):
            for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
                obj = context.get(name)
                if obj is not None:
                    return obj

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        return None

    def setup(self, context=None):
        if context is not None:
            self.context = context

        self.dispatcher = self._resolve_dispatcher(context or self.context)

        _register = globals().get("register_actions")
        if callable(_register) and self.dispatcher is not None:
            _sanhua_safe_call(_register, self.dispatcher)

        _legacy_setup = globals().get("setup")
        if callable(_legacy_setup):
            try:
                _sanhua_safe_call(_legacy_setup, context or self.context)
            except Exception:
                pass

        return {
            "ok": True,
            "module": "code_reader",
            "view": "setup",
            "dispatcher_ready": self.dispatcher is not None,
            "legacy_wrapped": True,
        }

    def start(self):
        _legacy_start = globals().get("start")
        if callable(_legacy_start):
            try:
                _sanhua_safe_call(_legacy_start)
            except Exception:
                pass

        self.started = True
        return {
            "ok": True,
            "module": "code_reader",
            "view": "start",
            "started": True,
        }

    def stop(self):
        _legacy_stop = globals().get("stop") or globals().get("shutdown")
        if callable(_legacy_stop):
            try:
                _sanhua_safe_call(_legacy_stop)
            except Exception:
                pass

        self.started = False
        return {
            "ok": True,
            "module": "code_reader",
            "view": "stop",
            "started": False,
        }

    def health_check(self):
        _legacy_health = globals().get("health_check")
        if callable(_legacy_health):
            try:
                result = _sanhua_safe_call(_legacy_health)
                if isinstance(result, dict):
                    result.setdefault("ok", True)
                    result.setdefault("module", "code_reader")
                    result.setdefault("view", "health_check")
                    return result
                return {
                    "ok": True,
                    "module": "code_reader",
                    "view": "health_check",
                    "data": result,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "module": "code_reader",
                    "view": "health_check",
                    "reason": str(e),
                }

        return {
            "ok": True,
            "module": "code_reader",
            "view": "health_check",
            "started": self.started,
            "legacy_wrapped": True,
        }

    def preload(self):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 无需复杂预加载时，默认返回成功。
        """
        return {
            "ok": True,
            "module": "code_reader",
            "view": "preload",
            "started": self.started,
            "wrapper": "OfficialCodeReaderModule",
            "legacy_wrapped": True,
        }
    def handle_event(self, event_name, payload=None):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 默认不消费事件，返回 noop/ignored。
        """
        return {
            "ok": True,
            "module": "code_reader",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "handled": False,
            "reason": "noop_legacy_wrapper",
            "wrapper": "OfficialCodeReaderModule",
        }

def official_entry(context=None):
    _instance = OfficialCodeReaderModule(context=context)
    _instance.setup(context=context)
    return _instance
# === SANHUA_OFFICIAL_WRAPPER_END ===
