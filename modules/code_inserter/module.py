from __future__ import annotations

import difflib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("code_inserter")


def _now_ts() -> int:
    return int(time.time())


def _clip(text: str, limit: int = 1200) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def _line_hint(start_line: int, end_line: int) -> str:
    if start_line <= 0:
        start_line = 1
    if end_line <= 0:
        end_line = start_line
    if start_line == end_line:
        return f"L{start_line}"
    return f"L{start_line}-L{end_line}"


def _is_relative_to(path_obj: Path, base: Path) -> bool:
    try:
        path_obj.relative_to(base)
        return True
    except Exception:
        return False


def _read_text(path_obj: Path) -> str:
    try:
        return path_obj.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path_obj.read_text(encoding="utf-8", errors="replace")


def _build_diff_preview(
    before_text: str,
    after_text: str,
    path_obj: Path,
    max_chars: int = 3000,
) -> Tuple[str, bool]:
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)

    diff = "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{path_obj} (before)",
            tofile=f"{path_obj} (after-preview)",
            lineterm="",
            n=3,
        )
    )
    if len(diff) <= max_chars:
        return diff, False
    return diff[:max_chars] + "\n...[diff truncated]...", True


def _numbered_excerpt(
    text: str,
    start_line: int,
    end_line: int,
    pad: int = 2,
) -> str:
    lines = text.splitlines()
    if not lines:
        return ""

    total = len(lines)
    lo = max(1, start_line - pad)
    hi = min(total, end_line + pad)

    out: List[str] = []
    for lineno in range(lo, hi + 1):
        prefix = ">"
        if lineno < start_line or lineno > end_line:
            prefix = " "
        out.append(f"{prefix} {lineno:04d}: {lines[lineno - 1]}")
    return "\n".join(out)


def _tail_numbered_excerpt(text: str, pad: int = 4) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    total = len(lines)
    lo = max(1, total - pad + 1)
    out: List[str] = []
    for lineno in range(lo, total + 1):
        out.append(f"  {lineno:04d}: {lines[lineno - 1]}")
    return "\n".join(out)


def _estimate_risk(path_obj: Path, old_text: str, new_text: str) -> str:
    hay = "\n".join([old_text or "", new_text or ""]).lower()

    high_markers = (
        "eval(",
        "exec(",
        "subprocess",
        "os.remove",
        "os.rmdir",
        "shutil.rmtree",
        "rm -rf",
        "chmod 777",
        "drop table",
    )
    medium_markers = (
        "def ",
        "class ",
        "import ",
        "from ",
        "except exception",
        "__init__",
        "manifest",
        "yaml",
        "json",
    )

    if any(marker in hay for marker in high_markers):
        return "high"

    line_delta = abs((new_text or "").count("\n") - (old_text or "").count("\n"))
    size_delta = abs(len(new_text or "") - len(old_text or ""))

    if any(marker in hay for marker in medium_markers):
        return "medium"

    if path_obj.suffix == ".py" and (line_delta >= 8 or size_delta >= 300):
        return "medium"

    if path_obj.suffix in (".yaml", ".yml", ".json") and size_delta >= 120:
        return "medium"

    return "low"


class CodeInserterModule:
    def __init__(self, root_dir: Optional[str] = None, backup_dir: Optional[str] = None) -> None:
        self.root_dir = Path(root_dir or Path(__file__).resolve().parents[2]).resolve()
        self.backup_dir = Path(backup_dir or (Path.home() / ".aicore" / "backups")).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.started = False
        log.info("代码插入器初始化完成，备份目录: %s", self.backup_dir)

    # ---------------------------------------------------------
    # 生命周期 / 健康检查
    # ---------------------------------------------------------

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> bool:
        self.started = False
        return True

    def health_check(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "source": "code_inserter_module",
            "started": self.started,
            "root_dir": str(self.root_dir),
            "backup_dir": str(self.backup_dir),
            "timestamp": _now_ts(),
        }

    # ---------------------------------------------------------
    # 路径 / 文件
    # ---------------------------------------------------------

    def _resolve_repo_path(self, path: str) -> Path:
        if not path:
            raise ValueError("missing_path")

        raw = Path(path)
        if raw.is_absolute():
            abs_path = raw.resolve()
        else:
            abs_path = (self.root_dir / raw).resolve()

        if not _is_relative_to(abs_path, self.root_dir):
            raise ValueError("path_outside_repo")

        return abs_path

    # ---------------------------------------------------------
    # preview_replace_text
    # ---------------------------------------------------------

    def action_preview_replace_text(
        self,
        context: Optional[Dict[str, Any]] = None,
        *,
        path: str,
        old: str,
        new: str,
        occurrence: int = 1,
        excerpt_pad: int = 2,
        diff_max_chars: int = 3000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}
        path_obj = self._resolve_repo_path(path)

        if not path_obj.exists():
            return {
                "ok": False,
                "error": "file_not_found",
                "reason": "file_not_found",
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_replace_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        if path_obj.is_dir():
            return {
                "ok": False,
                "error": "path_is_dir",
                "reason": "path_is_dir",
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_replace_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        before_text = _read_text(path_obj)
        if old is None or old == "":
            return {
                "ok": False,
                "error": "missing_old",
                "reason": "missing_old",
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_replace_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        matches: List[int] = []
        scan_from = 0
        step = max(1, len(old))
        while True:
            idx = before_text.find(old, scan_from)
            if idx < 0:
                break
            matches.append(idx)
            scan_from = idx + step

        if not matches:
            return {
                "ok": False,
                "error": "pattern_not_found",
                "reason": "pattern_not_found",
                "match_count": 0,
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_replace_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        if occurrence < 1 or occurrence > len(matches):
            return {
                "ok": False,
                "error": "invalid_occurrence",
                "reason": "invalid_occurrence",
                "match_count": len(matches),
                "occurrence": occurrence,
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_replace_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        start_idx = matches[occurrence - 1]
        end_idx = start_idx + len(old)

        after_text = before_text[:start_idx] + new + before_text[end_idx:]

        start_line = before_text.count("\n", 0, start_idx) + 1
        end_line_before = start_line + max(1, old.count("\n") + 1) - 1
        end_line_after = start_line + max(1, (new or "").count("\n") + 1) - 1

        context_before = _numbered_excerpt(
            before_text,
            start_line=start_line,
            end_line=end_line_before,
            pad=excerpt_pad,
        )
        context_after = _numbered_excerpt(
            after_text,
            start_line=start_line,
            end_line=end_line_after,
            pad=excerpt_pad,
        )

        diff_preview, diff_truncated = _build_diff_preview(
            before_text=before_text,
            after_text=after_text,
            path_obj=path_obj,
            max_chars=diff_max_chars,
        )

        estimated_risk = _estimate_risk(path_obj, old, new)
        changed = old != new
        replace_count = len(matches)

        return {
            "ok": True,
            "changed": changed,
            "path": str(path_obj),
            "source": "code_inserter_module",
            "view": "preview_replace_text",
            "timestamp": _now_ts(),
            "started": self.started,
            "match_count": len(matches),
            "replace_count": replace_count,
            "occurrence": occurrence,
            "line_start_before": start_line,
            "line_end_before": end_line_before,
            "line_end_after": end_line_after,
            "line_hint": _line_hint(start_line, end_line_after),
            "target_excerpt_before": _clip(old, 1200),
            "target_excerpt_after": _clip(new, 1200),
            "context_before": _clip(context_before, 1800),
            "context_after": _clip(context_after, 1800),
            "change_summary": (
                f"preview_replace_text: {path_obj} | "
                f"occurrence={occurrence}/{len(matches)} | "
                f"chars {len(old)} -> {len(new)} | "
                f"estimated_risk={estimated_risk}"
            ),
            "estimated_risk": estimated_risk,
            "diff_preview": diff_preview,
            "diff_truncated": diff_truncated,
        }

    # ---------------------------------------------------------
    # preview_append_text
    # ---------------------------------------------------------

    def action_preview_append_text(
        self,
        context: Optional[Dict[str, Any]] = None,
        *,
        path: str,
        text: str,
        excerpt_pad: int = 3,
        diff_max_chars: int = 3000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}
        path_obj = self._resolve_repo_path(path)

        if not path_obj.exists():
            return {
                "ok": False,
                "error": "file_not_found",
                "reason": "file_not_found",
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_append_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        if path_obj.is_dir():
            return {
                "ok": False,
                "error": "path_is_dir",
                "reason": "path_is_dir",
                "path": str(path_obj),
                "source": "code_inserter_module",
                "view": "preview_append_text",
                "timestamp": _now_ts(),
                "started": self.started,
            }

        append_text = text or ""
        before_text = _read_text(path_obj)
        after_text = before_text + append_text

        last_existing_line = max(1, before_text.count("\n") + 1)
        append_line_start = last_existing_line + (1 if before_text and before_text.endswith("\n") else 0)
        append_line_end = append_line_start + max(1, append_text.count("\n") + 1) - 1

        context_before = _tail_numbered_excerpt(before_text, pad=excerpt_pad + 2)
        context_after = _numbered_excerpt(
            after_text,
            start_line=max(1, append_line_start),
            end_line=max(append_line_start, append_line_end),
            pad=excerpt_pad,
        )

        diff_preview, diff_truncated = _build_diff_preview(
            before_text=before_text,
            after_text=after_text,
            path_obj=path_obj,
            max_chars=diff_max_chars,
        )

        estimated_risk = _estimate_risk(path_obj, "", append_text)

        return {
            "ok": True,
            "changed": bool(append_text),
            "path": str(path_obj),
            "source": "code_inserter_module",
            "view": "preview_append_text",
            "timestamp": _now_ts(),
            "started": self.started,
            "appended_chars": len(append_text),
            "line_start_after": append_line_start,
            "line_end_after": append_line_end,
            "line_hint": _line_hint(append_line_start, append_line_end),
            "target_excerpt_before": "",
            "target_excerpt_after": _clip(append_text, 1200),
            "context_before": _clip(context_before, 1800),
            "context_after": _clip(context_after, 1800),
            "change_summary": (
                f"preview_append_text: {path_obj} | "
                f"appended_chars={len(append_text)} | "
                f"estimated_risk={estimated_risk}"
            ),
            "estimated_risk": estimated_risk,
            "diff_preview": diff_preview,
            "diff_truncated": diff_truncated,
        }


_INSTANCE: Optional[CodeInserterModule] = None


def _get_instance() -> CodeInserterModule:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CodeInserterModule()
    return _INSTANCE


def action_preview_replace_text(context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    return _get_instance().action_preview_replace_text(context=context, **kwargs)


def action_preview_append_text(context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    return _get_instance().action_preview_append_text(context=context, **kwargs)


def register_actions(dispatcher: Any) -> Dict[str, Any]:
    instance = _get_instance()

    if hasattr(dispatcher, "register_action"):
        dispatcher.register_action(
            "code_inserter.preview_replace_text",
            instance.action_preview_replace_text,
            description="预演替换文本，返回 diff 和上下文，不真实写盘",
        )
        dispatcher.register_action(
            "code_inserter.preview_append_text",
            instance.action_preview_append_text,
            description="预演追加文本，返回 diff 和上下文，不真实写盘",
        )

    log.info("代码插入模块动作注册完成")
    return {
        "ok": True,
        "count": 2,
        "actions": [
            "code_inserter.preview_replace_text",
            "code_inserter.preview_append_text",
        ],
    }


entry = CodeInserterModule

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


class OfficialCodeInserterModule(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for legacy module: code_inserter
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
            "module": "code_inserter",
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
            "module": "code_inserter",
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
            "module": "code_inserter",
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
                    result.setdefault("module", "code_inserter")
                    result.setdefault("view", "health_check")
                    return result
                return {
                    "ok": True,
                    "module": "code_inserter",
                    "view": "health_check",
                    "data": result,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "module": "code_inserter",
                    "view": "health_check",
                    "reason": str(e),
                }

        return {
            "ok": True,
            "module": "code_inserter",
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
            "module": "code_inserter",
            "view": "preload",
            "started": self.started,
            "wrapper": "OfficialCodeInserterModule",
            "legacy_wrapped": True,
        }
    def handle_event(self, event_name, payload=None):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 默认不消费事件，返回 noop/ignored。
        """
        return {
            "ok": True,
            "module": "code_inserter",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "handled": False,
            "reason": "noop_legacy_wrapper",
            "wrapper": "OfficialCodeInserterModule",
        }

def official_entry(context=None):
    _instance = OfficialCodeInserterModule(context=context)
    _instance.setup(context=context)
    return _instance
# === SANHUA_OFFICIAL_WRAPPER_END ===
