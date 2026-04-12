#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class SelfEvolutionOrchestrator:
    """
    三花聚顶 · 自演化编排器（第一版）

    目标：
    1. 串起 read -> review -> syntax -> preview -> apply -> validate -> rollback
    2. 先做“文本替换 / 文本追加”两类低复杂度改动
    3. 正式落地仍走 AICore.safe_apply_change_set(...)，不绕开主控

    第一版能力边界：
    - 支持 replace_text / append_text
    - 支持 preview_only / 正式 apply 两种模式
    - 支持对 .py 文件自动追加 syntax 校验
    - 支持附加 import_module / action_exists / action_smoke 校验
    """

    def __init__(
        self,
        *,
        aicore: Any,
        root: Optional[str] = None,
    ) -> None:
        self.aicore = aicore
        self.root = Path(root or self._guess_root()).resolve()

    # ============================================================
    # public
    # ============================================================

    def run_text_replace_workflow(
        self,
        *,
        path: str,
        old: str,
        new: str,
        occurrence: int = 1,
        user_query: str = "",
        preview_only: bool = True,
        review_before: bool = True,
        review_after: bool = False,
        max_review_chars: int = 5000,
        extra_validation_checks: Optional[List[Dict[str, Any]]] = None,
        import_module_after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        跑“文本替换”闭环：
        - exists
        - read_before
        - syntax_before(.py)
        - review_before(可选)
        - preview_replace_text
        - safe_apply_change_set(可选)
        - read_after
        - syntax_after(.py)
        - review_after(可选)
        """
        started_at = int(time.time())
        abs_path = str(self._resolve_path(path))

        report: Dict[str, Any] = {
            "ok": False,
            "mode": "preview_only" if preview_only else "apply",
            "operation": "replace_text",
            "path": abs_path,
            "started_at": started_at,
            "user_query": user_query,
            "steps": {
                "exists": None,
                "read_before": None,
                "syntax_before": None,
                "review_before": None,
                "preview": None,
                "apply": None,
                "read_after": None,
                "syntax_after": None,
                "review_after": None,
            },
            "summary": "",
        }

        # 1) exists
        exists_out = self._invoke_action(
            "code_reader.exists",
            path=path,
        )
        report["steps"]["exists"] = exists_out
        if not self._action_ok(exists_out):
            report["summary"] = "code_reader.exists failed"
            return report

        # 2) read_before
        read_before_out = self._invoke_action(
            "code_reader.read_file",
            path=path,
            max_chars=max_review_chars,
        )
        report["steps"]["read_before"] = read_before_out
        if not self._action_ok(read_before_out):
            report["summary"] = "code_reader.read_file(before) failed"
            return report

        # 3) syntax_before
        if self._is_python_path(path):
            syntax_before_out = self._invoke_action(
                "code_executor.syntax_file",
                path=path,
            )
            report["steps"]["syntax_before"] = syntax_before_out
            if not self._action_ok(syntax_before_out):
                report["summary"] = "code_executor.syntax_file(before) failed"
                return report

        # 4) review_before
        if review_before:
            review_before_out = self._invoke_action(
                "code_reviewer.review_file",
                path=path,
                max_chars=max_review_chars,
            )
            report["steps"]["review_before"] = review_before_out

        # 5) preview
        preview_out = self._invoke_action(
            "code_inserter.preview_replace_text",
            path=path,
            old=old,
            new=new,
            occurrence=occurrence,
        )
        report["steps"]["preview"] = preview_out
        if not self._action_ok(preview_out):
            report["summary"] = "code_inserter.preview_replace_text failed"
            return report

        if preview_only:
            report["ok"] = True
            report["summary"] = "preview_replace_text ok"
            return report

        # 6) apply + validate + rollback
        validation_checks = self._build_replace_validation_checks(
            path=path,
            new=new,
            extra_validation_checks=extra_validation_checks,
            import_module_after=import_module_after,
        )

        apply_out = self.aicore.safe_apply_change_set(
            operations=[
                {
                    "path": path,
                    "op": "replace_text",
                    "old": old,
                    "new": new,
                    "occurrence": occurrence,
                }
            ],
            reason=user_query or f"self_evolution.replace_text:{path}",
            metadata={
                "source": "self_evolution_orchestrator",
                "operation": "replace_text",
                "path": path,
            },
            dry_run=False,
            validation_checks=validation_checks,
        )
        report["steps"]["apply"] = apply_out
        if not apply_out.get("ok"):
            report["summary"] = "safe_apply_change_set failed or rolled back"
            return report

        # 7) read_after
        read_after_out = self._invoke_action(
            "code_reader.read_file",
            path=path,
            max_chars=max_review_chars,
        )
        report["steps"]["read_after"] = read_after_out

        # 8) syntax_after
        if self._is_python_path(path):
            syntax_after_out = self._invoke_action(
                "code_executor.syntax_file",
                path=path,
            )
            report["steps"]["syntax_after"] = syntax_after_out

        # 9) review_after
        if review_after:
            review_after_out = self._invoke_action(
                "code_reviewer.review_file",
                path=path,
                max_chars=max_review_chars,
            )
            report["steps"]["review_after"] = review_after_out

        report["ok"] = True
        report["summary"] = "replace_text workflow ok"
        return report

    def run_text_append_workflow(
        self,
        *,
        path: str,
        text: str,
        user_query: str = "",
        preview_only: bool = True,
        review_before: bool = True,
        review_after: bool = False,
        max_review_chars: int = 5000,
        extra_validation_checks: Optional[List[Dict[str, Any]]] = None,
        import_module_after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        跑“文本追加”闭环：
        - exists(可不存在)
        - read_before(不存在则允许跳过)
        - syntax_before(.py 且存在时)
        - review_before(可选)
        - preview_append_text
        - safe_apply_change_set(可选)
        - read_after
        - syntax_after(.py)
        - review_after(可选)
        """
        started_at = int(time.time())
        abs_path = str(self._resolve_path(path))

        report: Dict[str, Any] = {
            "ok": False,
            "mode": "preview_only" if preview_only else "apply",
            "operation": "append_text",
            "path": abs_path,
            "started_at": started_at,
            "user_query": user_query,
            "steps": {
                "exists": None,
                "read_before": None,
                "syntax_before": None,
                "review_before": None,
                "preview": None,
                "apply": None,
                "read_after": None,
                "syntax_after": None,
                "review_after": None,
            },
            "summary": "",
        }

        # 1) exists
        exists_out = self._invoke_action(
            "code_reader.exists",
            path=path,
        )
        report["steps"]["exists"] = exists_out
        existed_before = bool((exists_out.get("output") or {}).get("exists")) if exists_out.get("status") == "ok" else False

        # 2) read_before
        if existed_before:
            read_before_out = self._invoke_action(
                "code_reader.read_file",
                path=path,
                max_chars=max_review_chars,
            )
            report["steps"]["read_before"] = read_before_out
            if not self._action_ok(read_before_out):
                report["summary"] = "code_reader.read_file(before) failed"
                return report

        # 3) syntax_before
        if existed_before and self._is_python_path(path):
            syntax_before_out = self._invoke_action(
                "code_executor.syntax_file",
                path=path,
            )
            report["steps"]["syntax_before"] = syntax_before_out
            if not self._action_ok(syntax_before_out):
                report["summary"] = "code_executor.syntax_file(before) failed"
                return report

        # 4) review_before
        if review_before and existed_before:
            review_before_out = self._invoke_action(
                "code_reviewer.review_file",
                path=path,
                max_chars=max_review_chars,
            )
            report["steps"]["review_before"] = review_before_out

        # 5) preview
        preview_out = self._invoke_action(
            "code_inserter.preview_append_text",
            path=path,
            text=text,
        )
        report["steps"]["preview"] = preview_out
        if not self._action_ok(preview_out):
            report["summary"] = "code_inserter.preview_append_text failed"
            return report

        if preview_only:
            report["ok"] = True
            report["summary"] = "preview_append_text ok"
            return report

        # 6) apply + validate + rollback
        validation_checks = self._build_append_validation_checks(
            path=path,
            text=text,
            extra_validation_checks=extra_validation_checks,
            import_module_after=import_module_after,
        )

        apply_out = self.aicore.safe_apply_change_set(
            operations=[
                {
                    "path": path,
                    "op": "append_text",
                    "text": text,
                }
            ],
            reason=user_query or f"self_evolution.append_text:{path}",
            metadata={
                "source": "self_evolution_orchestrator",
                "operation": "append_text",
                "path": path,
            },
            dry_run=False,
            validation_checks=validation_checks,
        )
        report["steps"]["apply"] = apply_out
        if not apply_out.get("ok"):
            report["summary"] = "safe_apply_change_set failed or rolled back"
            return report

        # 7) read_after
        read_after_out = self._invoke_action(
            "code_reader.read_file",
            path=path,
            max_chars=max_review_chars,
        )
        report["steps"]["read_after"] = read_after_out

        # 8) syntax_after
        if self._is_python_path(path):
            syntax_after_out = self._invoke_action(
                "code_executor.syntax_file",
                path=path,
            )
            report["steps"]["syntax_after"] = syntax_after_out

        # 9) review_after
        if review_after:
            review_after_out = self._invoke_action(
                "code_reviewer.review_file",
                path=path,
                max_chars=max_review_chars,
            )
            report["steps"]["review_after"] = review_after_out

        report["ok"] = True
        report["summary"] = "append_text workflow ok"
        return report

    # ============================================================
    # internals
    # ============================================================

    def _guess_root(self) -> str:
        try:
            cfg = getattr(self.aicore, "config", None)
            root_dir = getattr(cfg, "root_dir", None)
            if root_dir:
                return str(Path(root_dir).resolve())
        except Exception:
            pass

        try:
            return str(Path(__file__).resolve().parents[3])
        except Exception:
            return str(Path.cwd().resolve())

    def _resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def _is_python_path(self, raw_path: str) -> bool:
        return str(raw_path).lower().endswith(".py")

    def _get_dispatcher(self) -> Any:
        for name in ("_best_dispatcher", "_resolve_dispatcher"):
            fn = getattr(self.aicore, name, None)
            if callable(fn):
                try:
                    obj = fn()
                    if obj is not None:
                        return obj
                except Exception:
                    pass

        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            try:
                obj = getattr(self.aicore, name, None)
                if obj is not None:
                    return obj
            except Exception:
                continue

        return None

    def _get_context(self) -> Any:
        for name in ("context", "ctx"):
            try:
                obj = getattr(self.aicore, name, None)
                if obj is not None and callable(getattr(obj, "call_action", None)):
                    return obj
            except Exception:
                continue

        dispatcher = self._get_dispatcher()
        context = getattr(dispatcher, "context", None)
        if context is not None and callable(getattr(context, "call_action", None)):
            return context

        return None

    def _extract_callable_from_action_meta(self, meta: Any) -> Optional[Any]:
        if meta is None:
            return None

        for name in ("func", "handler", "callable", "callback", "action"):
            fn = getattr(meta, name, None)
            if callable(fn):
                return fn

        if callable(meta):
            return meta

        return None

    def _invoke_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        context = self._get_context()
        if context is not None:
            try:
                output = context.call_action(action_name, params=kwargs)
                return {
                    "status": self._status_from_output(output),
                    "action_name": action_name,
                    "output": output,
                    "bridge_method": "context.call_action(action_name, params=...)",
                    "invoke_mode": "context.call_action",
                }
            except Exception as exc:
                last_error = str(exc)
        else:
            last_error = None

        dispatcher = self._get_dispatcher()
        if dispatcher is None:
            return {
                "status": "failed",
                "action_name": action_name,
                "reason": last_error or "dispatcher_not_ready",
            }

        call_action = getattr(dispatcher, "call_action", None)
        if callable(call_action):
            try:
                output = call_action(action_name, params=kwargs)
                return {
                    "status": self._status_from_output(output),
                    "action_name": action_name,
                    "output": output,
                    "bridge_method": "compat:dispatcher.call_action(action_name, params=...)",
                    "invoke_mode": "compat:dispatcher.call_action",
                }
            except Exception as exc:
                last_error = str(exc)

        return {
            "status": "failed",
            "action_name": action_name,
            "reason": last_error or "no_action_bridge_available",
        }

    def _invoke_callable(self, fn: Any, kwargs: Dict[str, Any]) -> tuple[Any, str]:
        sig = inspect.signature(fn)
        params = sig.parameters
        accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

        context_value = {
            "source": "self_evolution_orchestrator",
            "timestamp": int(time.time()),
        }

        local_kwargs = dict(kwargs)

        def _filtered(source_kwargs: Dict[str, Any]) -> Dict[str, Any]:
            if accepts_var_kw:
                return dict(source_kwargs)
            return {k: v for k, v in source_kwargs.items() if k in params}

        candidates = []

        if "context" in params:
            kw = _filtered(local_kwargs)
            kw_no_context = dict(kw)
            kw_no_context.pop("context", None)
            candidates.append(("callable(context=..., **kwargs)", lambda: fn(context=context_value, **kw_no_context)))
            candidates.append(("callable(context=..., kwargs-only)", lambda: fn(context=context_value)))
        else:
            kw = _filtered(local_kwargs)
            candidates.append(("callable(**kwargs)", lambda: fn(**kw)))
            candidates.append(("callable()", lambda: fn()))

        last_error = None
        for label, runner in candidates:
            try:
                return runner(), label
            except TypeError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        return fn(), "callable()"

    def _status_from_output(self, output: Any) -> str:
        if isinstance(output, dict) and output.get("ok") is False:
            return "failed"
        return "ok"

    def _action_ok(self, action_result: Optional[Dict[str, Any]]) -> bool:
        if not action_result:
            return False
        return action_result.get("status") == "ok"

    def _build_replace_validation_checks(
        self,
        *,
        path: str,
        new: str,
        extra_validation_checks: Optional[List[Dict[str, Any]]] = None,
        import_module_after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = [
            {"kind": "file_exists", "path": path},
        ]

        if new:
            checks.append(
                {"kind": "text_contains", "path": path, "needle": new}
            )

        if self._is_python_path(path):
            checks.append(
                {"kind": "syntax_file", "path": path}
            )

        if import_module_after:
            checks.append(
                {"kind": "import_module", "module": import_module_after}
            )

        if extra_validation_checks:
            checks.extend(extra_validation_checks)

        return checks

    def _build_append_validation_checks(
        self,
        *,
        path: str,
        text: str,
        extra_validation_checks: Optional[List[Dict[str, Any]]] = None,
        import_module_after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = [
            {"kind": "file_exists", "path": path},
        ]

        if text:
            checks.append(
                {"kind": "text_contains", "path": path, "needle": text}
            )

        if self._is_python_path(path):
            checks.append(
                {"kind": "syntax_file", "path": path}
            )

        if import_module_after:
            checks.append(
                {"kind": "import_module", "module": import_module_after}
            )

        if extra_validation_checks:
            checks.extend(extra_validation_checks)

        return checks
