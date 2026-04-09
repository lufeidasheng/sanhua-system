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

import ast
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


def _safe_register_action(dispatcher: Any, action_name: str, func: Any, description: str = "") -> None:
    """
    兼容不同 dispatcher.register_action 签名。
    """
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


class CodeExecutorModule:
    """
    安全正式版：
    - 只提供语法检查，不提供任意代码真实执行
    - 适合先接入决策链自动放行
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
            "source": "code_executor_module",
            "started": self.started,
            "timestamp": _now_ts(),
            "view": "health_check",
        }

    def _syntax_check_core(self, text: str, target: str, *, source_view: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        base = {
            "ok": True,
            "syntax_ok": True,
            "target": target,
            "source": "code_executor_module",
            "started": self.started,
            "timestamp": _now_ts(),
            "view": source_view,
        }
        if extra:
            base.update(extra)

        try:
            ast.parse(text, filename=target)
            compile(text, target, "exec")
            base["summary"] = f"syntax_check ok: {target}"
            return base
        except SyntaxError as e:
            return {
                **base,
                "ok": False,
                "syntax_ok": False,
                "error": "syntax_error",
                "reason": "syntax_error",
                "lineno": getattr(e, "lineno", None),
                "offset": getattr(e, "offset", None),
                "text": (getattr(e, "text", None) or "").rstrip(),
                "message": str(e),
                "summary": f"syntax_check failed: {target}",
            }
        except Exception as e:
            return {
                **base,
                "ok": False,
                "syntax_ok": False,
                "error": "syntax_check_failed",
                "reason": str(e),
                "message": str(e),
                "summary": f"syntax_check exception: {target}",
            }

    def action_syntax_check(
        self,
        context: Optional[Dict[str, Any]] = None,
        text: Optional[str] = None,
        path: Optional[str] = None,
        max_bytes: int = 512000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}

        if text is None:
            text = context.get("text")
        if path is None:
            path = context.get("path")
        if "max_bytes" in context:
            try:
                max_bytes = int(context.get("max_bytes"))
            except Exception:
                pass

        if text:
            return self._syntax_check_core(
                text=text,
                target="<inline_text>",
                source_view="syntax_check",
                extra={"mode": "inline"},
            )

        if not path:
            return {
                "ok": False,
                "syntax_ok": False,
                "error": "missing_input",
                "reason": "missing_input",
                "message": "需要提供 text 或 path",
                "source": "code_executor_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "syntax_check",
            }

        p = _resolve_path(str(path), context)
        if not p.exists():
            return {
                "ok": False,
                "syntax_ok": False,
                "error": "file_not_found",
                "reason": "file_not_found",
                "path": str(p),
                "source": "code_executor_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "syntax_check",
            }

        if not p.is_file():
            return {
                "ok": False,
                "syntax_ok": False,
                "error": "not_a_file",
                "reason": "not_a_file",
                "path": str(p),
                "source": "code_executor_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "syntax_check",
            }

        try:
            if p.stat().st_size > max_bytes:
                return {
                    "ok": False,
                    "syntax_ok": False,
                    "error": "file_too_large",
                    "reason": "file_too_large",
                    "path": str(p),
                    "max_bytes": max_bytes,
                    "source": "code_executor_module",
                    "started": self.started,
                    "timestamp": _now_ts(),
                    "view": "syntax_check",
                }

            text_data = p.read_text(encoding="utf-8", errors="ignore")
            return self._syntax_check_core(
                text=text_data,
                target=str(p),
                source_view="syntax_check",
                extra={"mode": "file", "path": str(p), "size": len(text_data)},
            )
        except Exception as e:
            return {
                "ok": False,
                "syntax_ok": False,
                "error": "read_failed",
                "reason": str(e),
                "path": str(p),
                "source": "code_executor_module",
                "started": self.started,
                "timestamp": _now_ts(),
                "view": "syntax_check",
            }

    def action_syntax_file(
        self,
        context: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
        max_bytes: int = 512000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        context = context or {}
        if path is None:
            path = context.get("path")
        return self.action_syntax_check(
            context=context,
            text=None,
            path=path,
            max_bytes=max_bytes,
            **kwargs,
        )


def entry(*args: Any, **kwargs: Any) -> CodeExecutorModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = CodeExecutorModule()
    return _MODULE_SINGLETON


def register_actions(dispatcher: Any) -> None:
    mod = entry()

    if hasattr(dispatcher, "get_action"):
        try:
            if dispatcher.get_action("code_executor.syntax_check") is None:
                _safe_register_action(
                    dispatcher,
                    "code_executor.syntax_check",
                    mod.action_syntax_check,
                    "检查 inline 文本或文件的 Python 语法",
                )
        except Exception:
            _safe_register_action(
                dispatcher,
                "code_executor.syntax_check",
                mod.action_syntax_check,
                "检查 inline 文本或文件的 Python 语法",
            )
    else:
        _safe_register_action(
            dispatcher,
            "code_executor.syntax_check",
            mod.action_syntax_check,
            "检查 inline 文本或文件的 Python 语法",
        )

    if hasattr(dispatcher, "get_action"):
        try:
            if dispatcher.get_action("code_executor.syntax_file") is None:
                _safe_register_action(
                    dispatcher,
                    "code_executor.syntax_file",
                    mod.action_syntax_file,
                    "检查文件的 Python 语法",
                )
        except Exception:
            _safe_register_action(
                dispatcher,
                "code_executor.syntax_file",
                mod.action_syntax_file,
                "检查文件的 Python 语法",
            )
    else:
        _safe_register_action(
            dispatcher,
            "code_executor.syntax_file",
            mod.action_syntax_file,
            "检查文件的 Python 语法",
        )

    log.info("代码执行器安全动作注册完成")
'''

INIT_PY = r'''# -*- coding: utf-8 -*-

from .module import CodeExecutorModule, entry, register_actions

__all__ = [
    "CodeExecutorModule",
    "entry",
    "register_actions",
]
'''


def backup_file(src: Path, backup_root: Path) -> None:
    dst = backup_root / src.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)
        print(f"[BACKUP ] {dst}")


def write_file(path: Path, content: str, backup_root: Path) -> None:
    backup_file(path, backup_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    print(f"[PATCHED] {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="patch code_executor official")
    parser.add_argument("--root", required=True, help="project root")
    args = parser.parse_args()

    ROOT = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = ROOT / "audit_output" / "fix_backups" / ts

    module_py = ROOT / "modules" / "code_executor" / "module.py"
    init_py = ROOT / "modules" / "code_executor" / "__init__.py"

    print("=" * 72)
    print("code_executor 正式模块补丁开始")
    print("=" * 72)

    write_file(module_py, MODULE_PY, backup_root)
    write_file(init_py, INIT_PY, backup_root)

    print("=" * 72)
    print("code_executor 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{ROOT / "tools" / "patch_decision_chain_whitelist_v6.py"}" --root "{ROOT}"')
    print("=" * 72)
