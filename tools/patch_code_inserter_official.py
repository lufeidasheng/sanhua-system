#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import shutil
from datetime import datetime
from pathlib import Path
import textwrap


MODULE_PY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import difflib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


def _now_ts() -> int:
    return int(time.time())


def _project_root_from_context(context: Optional[Dict[str, Any]] = None) -> Path:
    context = context or {}
    root = context.get("root") or context.get("project_root") or os.getcwd()
    return Path(root).resolve()


def _resolve_path(path_value: str, context: Optional[Dict[str, Any]] = None) -> Path:
    p = Path(path_value)
    if p.is_absolute():
        return p.resolve()
    return (_project_root_from_context(context) / p).resolve()


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _build_diff(old_text: str, new_text: str, fromfile: str, tofile: str, max_chars: int = 4000) -> tuple[str, bool]:
    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    return _truncate_text(diff, max_chars=max_chars)


def _safe_register_action(dispatcher: Any, action_name: str, func: Any, description: str = "") -> None:
    last_error = None
    candidates = [
        lambda: dispatcher.register_action(action_name, func, description),
        lambda: dispatcher.register_action(action_name, func),
        lambda: dispatcher.register_action(action_name=action_name, func=func, description=description),
        lambda: dispatcher.register_action(name=action_name, func=func, description=description),
        lambda: dispatcher.register_action(action_name=action_name, callback=func, description=description),
        lambda: dispatcher.register_action(name=action_name, callback=func, description=description),
    ]
    for runner in candidates:
        try:
            runner()
            return
        except Exception as e:
            last_error = e
    raise RuntimeError(f"register_action 失败: {last_error}")


class CodeInserterModule:
    """
    安全正式版：
    - 只做 preview，不做真实写入
    - 供决策链低风险放行
    """

    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def health_check(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "source": "code_inserter_module",
            "started": self.started,
            "timestamp": _now_ts(),
            "view": "health_check",
        }

    def _read_file(self, path_value: str, context: Optional[Dict[str, Any]] = None) -> tuple[Optional[Path], Optional[str], Optional[Dict[str, Any]]]:
        p = _resolve_path(path_value, context)

        if not p.exists():
            return None, None, {
                "ok": False,
                "error": "file_not_found",
                "reason": "file_not_found",
                "path": str(p),
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
            }

        if not p.is_file():
            return None, None, {
                "ok": False,
                "error": "not_a_file",
                "reason": "not_a_file",
                "path": str(p),
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
            }

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            return p, text, None
        except Exception as e:
            return None, None, {
                "ok": False,
                "error": "read_failed",
                "reason": str(e),
                "path": str(p),
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
            }

    def action_preview_replace_text(
        self,
        context: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
        old: Optional[str] = None,
        new: Optional[str] = None,
        occurrence: int = 1,
        max_diff_chars: int = 4000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}

        if path is None:
            path = context.get("path")
        if old is None:
            old = context.get("old")
        if new is None:
            new = context.get("new")
        if "occurrence" in context:
            try:
                occurrence = int(context.get("occurrence"))
            except Exception:
                pass
        if "max_diff_chars" in context:
            try:
                max_diff_chars = int(context.get("max_diff_chars"))
            except Exception:
                pass

        if not path or old is None or new is None:
            return {
                "ok": False,
                "error": "missing_input",
                "reason": "missing_input",
                "message": "需要 path / old / new",
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "preview_replace_text",
            }

        resolved_path, original_text, err = self._read_file(path, context)
        if err:
            err["view"] = "preview_replace_text"
            return err

        match_count = original_text.count(old)
        if match_count <= 0:
            return {
                "ok": False,
                "error": "pattern_not_found",
                "reason": "pattern_not_found",
                "path": str(resolved_path),
                "match_count": 0,
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "preview_replace_text",
            }

        if occurrence < 1:
            occurrence = 1

        replaced = original_text
        current_idx = 0
        for _ in range(occurrence):
            pos = replaced.find(old, current_idx)
            if pos < 0:
                return {
                    "ok": False,
                    "error": "occurrence_out_of_range",
                    "reason": "occurrence_out_of_range",
                    "path": str(resolved_path),
                    "match_count": match_count,
                    "occurrence": occurrence,
                    "source": "code_inserter_module",
                    "started": self.started,
                    "timestamp": _now_ts(),
                    "view": "preview_replace_text",
                }
            replaced = replaced[:pos] + new + replaced[pos + len(old):]
            current_idx = pos + len(new)

        diff_preview, truncated = _build_diff(
            original_text,
            replaced,
            fromfile=f"{resolved_path} (before)",
            tofile=f"{resolved_path} (after-preview)",
            max_chars=max_diff_chars,
        )

        return {
            "ok": True,
            "changed": original_text != replaced,
            "path": str(resolved_path),
            "match_count": match_count,
            "occurrence": occurrence,
            "diff_preview": diff_preview,
            "diff_truncated": truncated,
            "source": "code_inserter_module",
            "started": self.started,
            "timestamp": _now_ts(),
            "view": "preview_replace_text",
            "summary": f"preview_replace_text ok: {resolved_path}",
        }

    def action_preview_append_text(
        self,
        context: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
        text: Optional[str] = None,
        ensure_newline: bool = True,
        max_diff_chars: int = 4000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}

        if path is None:
            path = context.get("path")
        if text is None:
            text = context.get("text")
        if "ensure_newline" in context:
            ensure_newline = bool(context.get("ensure_newline"))
        if "max_diff_chars" in context:
            try:
                max_diff_chars = int(context.get("max_diff_chars"))
            except Exception:
                pass

        if not path or text is None:
            return {
                "ok": False,
                "error": "missing_input",
                "reason": "missing_input",
                "message": "需要 path / text",
                "source": "code_inserter_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "preview_append_text",
            }

        resolved_path, original_text, err = self._read_file(path, context)
        if err:
            err["view"] = "preview_append_text"
            return err

        appended = original_text
        if ensure_newline and appended and not appended.endswith("\\n"):
            appended += "\\n"
        appended += text

        diff_preview, truncated = _build_diff(
            original_text,
            appended,
            fromfile=f"{resolved_path} (before)",
            tofile=f"{resolved_path} (after-preview)",
            max_chars=max_diff_chars,
        )

        return {
            "ok": True,
            "changed": original_text != appended,
            "path": str(resolved_path),
            "appended_chars": len(text),
            "diff_preview": diff_preview,
            "diff_truncated": truncated,
            "source": "code_inserter_module",
            "started": self.started,
            "timestamp": _now_ts(),
            "view": "preview_append_text",
            "summary": f"preview_append_text ok: {resolved_path}",
        }


def entry(*args: Any, **kwargs: Any) -> CodeInserterModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = CodeInserterModule()
    return _MODULE_SINGLETON


def register_actions(dispatcher: Any) -> None:
    mod = entry()

    for action_name, func, description in [
        (
            "code_inserter.preview_replace_text",
            mod.action_preview_replace_text,
            "预演文本替换，不真实写入文件",
        ),
        (
            "code_inserter.preview_append_text",
            mod.action_preview_append_text,
            "预演文本追加，不真实写入文件",
        ),
    ]:
        if hasattr(dispatcher, "get_action"):
            try:
                if dispatcher.get_action(action_name) is None:
                    _safe_register_action(dispatcher, action_name, func, description)
            except Exception:
                _safe_register_action(dispatcher, action_name, func, description)
        else:
            _safe_register_action(dispatcher, action_name, func, description)

    log.info("代码插入模块 preview 动作注册完成")
'''

INIT_PY = r'''# -*- coding: utf-8 -*-

from .module import CodeInserterModule, entry, register_actions

__all__ = [
    "CodeInserterModule",
    "entry",
    "register_actions",
]
'''


def backup_file(src: Path, backup_root: Path, root: Path) -> None:
    dst = backup_root / src.relative_to(root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)
        print(f"[BACKUP ] {dst}")


def write_file(path: Path, content: str, backup_root: Path, root: Path) -> None:
    backup_file(path, backup_root, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    print(f"[PATCHED] {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="patch code_inserter official")
    parser.add_argument("--root", required=True, help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    module_py = root / "modules" / "code_inserter" / "module.py"
    init_py = root / "modules" / "code_inserter" / "__init__.py"

    print("=" * 72)
    print("code_inserter 正式模块补丁开始")
    print("=" * 72)

    write_file(module_py, MODULE_PY, backup_root, root)
    write_file(init_py, INIT_PY, backup_root, root)

    print("=" * 72)
    print("code_inserter 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root / "tools" / "patch_decision_chain_whitelist_v7.py"}" --root "{root}"')
    print("=" * 72)
