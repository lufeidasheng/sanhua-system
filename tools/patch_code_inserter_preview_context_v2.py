#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

MODULE_CODE = r'''from __future__ import annotations

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
'''

INIT_CODE = '''# -*- coding: utf-8 -*-

from .module import CodeInserterModule, entry, register_actions

__all__ = [
    "CodeInserterModule",
    "entry",
    "register_actions",
]
'''


def backup_file(root: Path, file_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = file_path.relative_to(root)
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, backup_path)
    return backup_path


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    module_py = root / "modules" / "code_inserter" / "module.py"
    init_py = root / "modules" / "code_inserter" / "__init__.py"

    print("=" * 72)
    print("code_inserter preview context v2 正式补丁开始")
    print("=" * 72)

    if module_py.exists():
        backup_path = backup_file(root, module_py)
        print(f"[BACKUP ] {backup_path}")
    write_text(module_py, MODULE_CODE)
    print(f"[PATCHED] {module_py}")

    if init_py.exists():
        backup_path = backup_file(root, init_py)
        print(f"[BACKUP ] {backup_path}")
    write_text(init_py, INIT_CODE)
    print(f"[PATCHED] {init_py}")

    print("=" * 72)
    print("code_inserter preview context v2 正式补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root / "tools" / "test_code_inserter_preview_context_v2.py"}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
