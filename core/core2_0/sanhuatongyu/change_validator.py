#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import ast
import importlib
import json
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ValidationCheck:
    kind: str
    ok: bool
    target: str
    message: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    ok: bool
    summary: str
    checks: List[ValidationCheck] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
        }


class ChangeValidator:
    """
    改后验证器：
    - 文件存在
    - 文本命中
    - Python 语法
    - 模块导入
    - action 是否注册
    - action smoke 测试
    """

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = Path(root).resolve() if root else Path.cwd().resolve()

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def run_checks(
        self,
        checks: List[Dict[str, Any]],
        *,
        dispatcher: Optional[Any] = None,
    ) -> ValidationReport:
        out: List[ValidationCheck] = []

        for item in checks:
            kind = str(item.get("kind", "")).strip()
            try:
                if kind == "file_exists":
                    out.append(self._check_file_exists(item))
                elif kind == "text_contains":
                    out.append(self._check_text_contains(item))
                elif kind == "syntax_file":
                    out.append(self._check_syntax_file(item))
                elif kind == "import_module":
                    out.append(self._check_import_module(item))
                elif kind == "action_exists":
                    out.append(self._check_action_exists(item, dispatcher=dispatcher))
                elif kind == "action_smoke":
                    out.append(self._check_action_smoke(item, dispatcher=dispatcher))
                else:
                    out.append(
                        ValidationCheck(
                            kind=kind or "unknown",
                            ok=False,
                            target=str(item),
                            message="unknown_check_kind",
                        )
                    )
            except Exception as exc:
                out.append(
                    ValidationCheck(
                        kind=kind or "unknown",
                        ok=False,
                        target=str(item),
                        message=str(exc),
                        detail={"traceback": traceback.format_exc()},
                    )
                )

        all_ok = all(x.ok for x in out) if out else False
        summary = "all_checks_passed" if all_ok else "validation_failed"
        return ValidationReport(ok=all_ok, summary=summary, checks=out)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def _check_file_exists(self, item: Dict[str, Any]) -> ValidationCheck:
        raw_path = str(item["path"])
        p = self._resolve_path(raw_path)
        ok = p.exists()
        return ValidationCheck(
            kind="file_exists",
            ok=ok,
            target=str(p),
            message="exists" if ok else "not_found",
            detail={
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
            },
        )

    def _check_text_contains(self, item: Dict[str, Any]) -> ValidationCheck:
        raw_path = str(item["path"])
        needle = str(item["needle"])
        p = self._resolve_path(raw_path)

        if not p.exists():
            return ValidationCheck(
                kind="text_contains",
                ok=False,
                target=str(p),
                message="file_not_found",
            )

        text = p.read_text(encoding=item.get("encoding", "utf-8"))
        count = text.count(needle)
        return ValidationCheck(
            kind="text_contains",
            ok=count > 0,
            target=str(p),
            message="matched" if count > 0 else "needle_not_found",
            detail={
                "needle": needle,
                "match_count": count,
            },
        )

    def _check_syntax_file(self, item: Dict[str, Any]) -> ValidationCheck:
        raw_path = str(item["path"])
        p = self._resolve_path(raw_path)

        if not p.exists():
            return ValidationCheck(
                kind="syntax_file",
                ok=False,
                target=str(p),
                message="file_not_found",
            )

        if p.suffix != ".py":
            return ValidationCheck(
                kind="syntax_file",
                ok=False,
                target=str(p),
                message="not_python_file",
            )

        text = p.read_text(encoding=item.get("encoding", "utf-8"))
        try:
            ast.parse(text, filename=str(p))
            return ValidationCheck(
                kind="syntax_file",
                ok=True,
                target=str(p),
                message="syntax_ok",
            )
        except SyntaxError as exc:
            bad_line = ""
            try:
                lines = text.splitlines()
                if exc.lineno and 1 <= exc.lineno <= len(lines):
                    bad_line = lines[exc.lineno - 1]
            except Exception:
                pass

            return ValidationCheck(
                kind="syntax_file",
                ok=False,
                target=str(p),
                message="syntax_error",
                detail={
                    "lineno": exc.lineno,
                    "offset": exc.offset,
                    "text": bad_line,
                    "error": str(exc),
                },
            )

    def _check_import_module(self, item: Dict[str, Any]) -> ValidationCheck:
        module_name = str(item["module"])
        try:
            importlib.import_module(module_name)
            return ValidationCheck(
                kind="import_module",
                ok=True,
                target=module_name,
                message="import_ok",
            )
        except Exception as exc:
            return ValidationCheck(
                kind="import_module",
                ok=False,
                target=module_name,
                message="import_failed",
                detail={
                    "error": str(exc),
                },
            )

    def _check_action_exists(self, item: Dict[str, Any], *, dispatcher: Optional[Any]) -> ValidationCheck:
        action_name = str(item["action"])
        if dispatcher is None:
            return ValidationCheck(
                kind="action_exists",
                ok=False,
                target=action_name,
                message="dispatcher_not_ready",
            )

        get_action = getattr(dispatcher, "get_action", None)
        if not callable(get_action):
            return ValidationCheck(
                kind="action_exists",
                ok=False,
                target=action_name,
                message="dispatcher_get_action_missing",
            )

        meta = get_action(action_name)
        return ValidationCheck(
            kind="action_exists",
            ok=meta is not None,
            target=action_name,
            message="action_found" if meta is not None else "action_not_found",
        )

    def _check_action_smoke(self, item: Dict[str, Any], *, dispatcher: Optional[Any]) -> ValidationCheck:
        action_name = str(item["action"])
        kwargs = dict(item.get("kwargs") or {})

        if dispatcher is None:
            return ValidationCheck(
                kind="action_smoke",
                ok=False,
                target=action_name,
                message="dispatcher_not_ready",
            )

        execute = getattr(dispatcher, "execute", None)
        if not callable(execute):
            return ValidationCheck(
                kind="action_smoke",
                ok=False,
                target=action_name,
                message="dispatcher_execute_missing",
            )

        try:
            output = execute(action_name, **kwargs)
            if isinstance(output, dict) and output.get("ok") is False:
                return ValidationCheck(
                    kind="action_smoke",
                    ok=False,
                    target=action_name,
                    message=str(output.get("reason") or output.get("error") or "action_returned_ok_false"),
                    detail={"output": output},
                )

            return ValidationCheck(
                kind="action_smoke",
                ok=True,
                target=action_name,
                message="action_smoke_ok",
                detail={"output": output},
            )
        except Exception as exc:
            return ValidationCheck(
                kind="action_smoke",
                ok=False,
                target=action_name,
                message="action_smoke_failed",
                detail={"error": str(exc)},
            )
