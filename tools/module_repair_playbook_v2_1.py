#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Issue:
    code: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FixPlan:
    kind: str
    path: str
    relpath: str
    reason: str
    old_text: str
    new_text: str
    file_exists_before: bool = True
    validation_checks: List[Dict[str, Any]] = field(default_factory=list)
    preview_action: str = "code_inserter.preview_replace_text"
    syntax_gate: bool = False
    review_gate: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FixExecution:
    kind: str
    path: str
    relpath: str
    ok: bool
    mode: str
    reason: str = ""
    preview: Optional[Dict[str, Any]] = None
    review: Optional[Dict[str, Any]] = None
    syntax: Optional[Dict[str, Any]] = None
    apply: Optional[Dict[str, Any]] = None
    local_validation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleReport:
    module: str
    module_dir: str
    issues: List[Issue] = field(default_factory=list)
    plans: List[FixPlan] = field(default_factory=list)
    executions: List[FixExecution] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "module_dir": self.module_dir,
            "issues": [x.to_dict() for x in self.issues],
            "plans": [x.to_dict() for x in self.plans],
            "executions": [x.to_dict() for x in self.executions],
        }


# ============================================================
# 基础工具
# ============================================================

def log(*args, **kwargs) -> None:
    print(*args, **kwargs)


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def relpath_posix(path: Path, root: Path) -> str:
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_json_load(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        data = json.loads(safe_read_text(path))
        if isinstance(data, dict):
            return data, None
        return {}, "manifest_not_dict"
    except Exception as e:
        return None, str(e)


def write_json_text(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def camelize(name: str) -> str:
    parts = [p for p in name.replace("-", "_").split("_") if p]
    if not parts:
        return "Unknown"
    return "".join(p[:1].upper() + p[1:] for p in parts)


def extract_base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        chain = []
        cur = node
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.append(cur.id)
        return ".".join(reversed(chain))
    return ""


def discover_module_class_name(module_name: str, module_py: Path) -> str:
    fallback = f"{camelize(module_name)}Module"
    if not module_py.exists():
        return fallback

    try:
        tree = ast.parse(safe_read_text(module_py), filename=str(module_py))
    except Exception:
        return fallback

    classes: List[Tuple[str, List[str]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [extract_base_name(b) for b in node.bases]
            classes.append((node.name, bases))

    for name, bases in classes:
        if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
            return name

    for name, _ in classes:
        if name.endswith("Module"):
            return name

    if classes:
        return classes[0][0]

    return fallback


def normalize_init_content() -> str:
    return """# -*- coding: utf-8 -*-
\"\"\"
Auto-normalized module package bridge.

目的：
- 避免 __init__.py 对 entry / register_actions 做刚性导入
- 保持 package -> module.py 的兼容代理
\"\"\"

from importlib import import_module as _import_module

_module = _import_module(f"{__name__}.module")

entry = getattr(_module, "entry", None)
register_actions = getattr(_module, "register_actions", None)


def __getattr__(name):
    return getattr(_module, name)


def __dir__():
    return sorted(set(globals().keys()) | set(dir(_module)))


__all__ = ["entry", "register_actions"]
"""


def needs_init_normalize(current: str, target: str) -> Tuple[bool, str]:
    if not current:
        return True, "__init__.py missing"

    cur = current.strip()
    tgt = target.strip()
    if cur == tgt:
        return False, ""

    if "from .module import" in current:
        return True, "strict_import_from_module"

    if "_import_module" not in current or "__getattr__" not in current:
        return True, "legacy_init_bridge"

    return False, ""


def build_normalized_manifest(
    current: Dict[str, Any],
    module_name: str,
    entry_class: str,
) -> Tuple[Dict[str, Any], List[str]]:
    data = dict(current or {})
    changes: List[str] = []

    if data.get("name") != module_name:
        data["name"] = module_name
        changes.append("fix:name")

    if data.get("entry") != "module.py":
        data["entry"] = "module.py"
        changes.append("fix:entry")

    if data.get("entry_class") != entry_class:
        data["entry_class"] = entry_class
        changes.append("fix:entry_class")

    if not data.get("status"):
        enabled = data.get("enabled", True)
        data["status"] = "active" if enabled else "disabled"
        changes.append("fill:status")

    if "market_compatible" not in data:
        data["market_compatible"] = True
        changes.append("fill:market_compatible")

    preferred_order = [
        "name",
        "version",
        "title",
        "author",
        "author_contact",
        "description",
        "license",
        "repository",
        "entry",
        "entry_class",
        "enabled",
        "entry_points",
        "icon",
        "health_check",
        "hot_pluggable",
        "singleton",
        "status",
        "categories",
        "tags",
        "dependencies",
        "actions",
        "events",
        "config_schema",
        "market_compatible",
    ]

    ordered: Dict[str, Any] = {}
    for key in preferred_order:
        if key in data:
            ordered[key] = data[key]
    for key, value in data.items():
        if key not in ordered:
            ordered[key] = value

    return ordered, changes


def make_unified_diff(old_text: str, new_text: str, path: str, after_label: str = "(after-preview)") -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{path} (before)",
        tofile=f"{path} {after_label}",
        lineterm="",
    )
    return "".join(diff)


def local_validate_plan(plan: FixPlan, text: str) -> Dict[str, Any]:
    try:
        if plan.extra.get("file_type") == "json":
            json.loads(text)
            return {"ok": True, "summary": "json_valid"}
        if plan.extra.get("file_type") == "python":
            compile(text, plan.path, "exec")
            return {"ok": True, "summary": "python_syntax_ok"}
        return {"ok": True, "summary": "no_extra_validation"}
    except Exception as e:
        return {"ok": False, "summary": str(e)}


def run_local_validation_checks(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []

    for check in checks or []:
        kind = str(check.get("kind") or "").strip()
        target = str(check.get("target") or "").strip()
        target_path = Path(target)

        if kind == "file_exists":
            ok = target_path.exists()
            results.append({
                "kind": kind,
                "target": target,
                "ok": ok,
                "message": "exists" if ok else "missing",
                "detail": {
                    "is_file": target_path.is_file(),
                    "is_dir": target_path.is_dir(),
                },
            })
            continue

        if kind == "text_contains":
            needle = str(check.get("needle") or "")
            text = safe_read_text(target_path)
            match_count = text.count(needle) if needle else 0
            ok = bool(needle) and (match_count > 0)
            results.append({
                "kind": kind,
                "target": target,
                "ok": ok,
                "message": "matched" if ok else "not_matched",
                "detail": {
                    "needle": needle,
                    "match_count": match_count,
                },
            })
            continue

        if kind == "syntax_file":
            try:
                text = safe_read_text(target_path)
                compile(text, str(target_path), "exec")
                results.append({
                    "kind": kind,
                    "target": target,
                    "ok": True,
                    "message": "syntax_ok",
                    "detail": {},
                })
            except Exception as e:
                lineno = getattr(e, "lineno", None)
                offset = getattr(e, "offset", None)
                err_text = getattr(e, "text", None)
                results.append({
                    "kind": kind,
                    "target": target,
                    "ok": False,
                    "message": "syntax_error",
                    "detail": {
                        "error": str(e),
                        "lineno": lineno,
                        "offset": offset,
                        "text": err_text.strip("\n") if isinstance(err_text, str) else err_text,
                    },
                })
            continue

        results.append({
            "kind": kind,
            "target": target,
            "ok": False,
            "message": "unsupported_check_kind",
            "detail": check,
        })

    ok = all(x.get("ok") for x in results) if results else True
    return {
        "ok": ok,
        "summary": "all_checks_passed" if ok else "validation_failed",
        "checks": results,
    }


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp_module_repair")
    tmp_path.write_text(text, encoding=encoding)
    tmp_path.replace(path)


# ============================================================
# AICore 安全栈桥接
# ============================================================

class AICoreBridge:
    def __init__(self, root: Path):
        self.root = root.resolve()
        ensure_sys_path(self.root)
        os.chdir(self.root)

        from core.aicore.aicore import get_aicore_instance  # noqa

        self.aicore = get_aicore_instance()
        self.bootstrap_info = None

        if hasattr(self.aicore, "_bootstrap_action_registry"):
            try:
                self.bootstrap_info = self.aicore._bootstrap_action_registry(force=True)
            except Exception as e:
                self.bootstrap_info = {"ok": False, "reason": str(e)}

    def process_action(
        self,
        action_name: str,
        *,
        runtime_context: Optional[Dict[str, Any]] = None,
        user_query: str = "",
    ) -> Dict[str, Any]:
        text = f"1. 调用 {action_name} 执行动作"
        result = self.aicore.process_suggestion_chain(
            text,
            user_query=user_query or f"invoke {action_name}",
            runtime_context=runtime_context or {},
            dry_run=False,
        )
        step_results = ((result.get("execution") or {}).get("step_results") or [])
        step = step_results[0] if step_results else {}
        return {
            "ok": step.get("status") == "ok",
            "raw": result,
            "step": step,
        }

    def safe_apply(
        self,
        operations: List[Dict[str, Any]],
        *,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        validation_checks: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self.aicore.safe_apply_change_set(
            operations,
            reason=reason,
            metadata=metadata,
            dry_run=dry_run,
            validation_checks=validation_checks or [],
        )

    def create_snapshot(
        self,
        paths: List[str],
        *,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.aicore.create_rollback_snapshot(paths, reason=reason, metadata=metadata)

    def rollback_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        return self.aicore.rollback_snapshot(snapshot_id)

    def validate_change_set(self, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.aicore.validate_change_set(checks, dispatcher=self.resolve_dispatcher())

    def resolve_dispatcher(self) -> Any:
        resolver = getattr(self.aicore, "_resolve_dispatcher", None)
        if callable(resolver):
            try:
                return resolver()
            except Exception:
                return None
        return None


# ============================================================
# 分析器
# ============================================================

def analyze_module(module_dir: Path, root: Path) -> ModuleReport:
    module_name = module_dir.name
    report = ModuleReport(module=module_name, module_dir=str(module_dir))

    module_py = module_dir / "module.py"
    init_py = module_dir / "__init__.py"
    manifest_json = module_dir / "manifest.json"

    # ---------- init ----------
    init_target = normalize_init_content()
    init_current = safe_read_text(init_py)
    need_init, init_reason = needs_init_normalize(init_current, init_target)
    if need_init:
        report.issues.append(Issue(code="INIT_NEEDS_NORMALIZE", detail=init_reason))
        report.plans.append(
            FixPlan(
                kind="normalize_init",
                path=str(init_py),
                relpath=relpath_posix(init_py, root),
                reason=init_reason,
                old_text=init_current,
                new_text=init_target,
                file_exists_before=init_py.exists(),
                preview_action="code_inserter.preview_replace_text",
                syntax_gate=True,
                review_gate=True,
                validation_checks=[
                    {"kind": "file_exists", "target": str(init_py)},
                    {"kind": "text_contains", "target": str(init_py), "needle": "_module = _import_module"},
                    {"kind": "syntax_file", "target": str(init_py)},
                ],
                extra={"file_type": "python"},
            )
        )

    # ---------- manifest ----------
    manifest_obj, manifest_error = safe_json_load(manifest_json)
    if manifest_error is not None and manifest_obj is None:
        report.issues.append(Issue(code="MANIFEST_INVALID_JSON", detail=manifest_error))
    else:
        manifest_current_obj = manifest_obj or {}
        raw_manifest_text = safe_read_text(manifest_json) if manifest_json.exists() else ""

        class_name = discover_module_class_name(module_name, module_py)
        entry_class = f"modules.{module_name}.module.{class_name}"

        manifest_target_obj, manifest_changes = build_normalized_manifest(
            manifest_current_obj,
            module_name,
            entry_class,
        )
        manifest_target_text = write_json_text(manifest_target_obj)

        if manifest_changes:
            report.issues.append(
                Issue(code="MANIFEST_NEEDS_NORMALIZE", detail=", ".join(manifest_changes))
            )
            report.plans.append(
                FixPlan(
                    kind="normalize_manifest",
                    path=str(manifest_json),
                    relpath=relpath_posix(manifest_json, root),
                    reason=", ".join(manifest_changes),
                    old_text=raw_manifest_text,
                    new_text=manifest_target_text,
                    file_exists_before=manifest_json.exists(),
                    preview_action="code_inserter.preview_replace_text",
                    syntax_gate=False,
                    review_gate=False,
                    validation_checks=[
                        {"kind": "file_exists", "target": str(manifest_json)},
                        {"kind": "text_contains", "target": str(manifest_json), "needle": "\"entry\": \"module.py\""},
                    ],
                    extra={
                        "file_type": "json",
                        "entry_class": entry_class,
                    },
                )
            )

    return report


# ============================================================
# 执行器
# ============================================================

def synthetic_preview_for_missing_file(plan: FixPlan) -> Dict[str, Any]:
    diff_preview = make_unified_diff("", plan.new_text, plan.path)
    output = {
        "ok": True,
        "source": "module_repair_playbook_v2_2",
        "view": "synthetic_create_preview",
        "path": plan.path,
        "change_summary": f"create_file preview: {plan.path}",
        "estimated_risk": "low" if plan.extra.get("file_type") in ("python", "json") else "medium",
        "target_excerpt_before": "",
        "target_excerpt_after": plan.new_text[:500],
        "context_before": "",
        "context_after": plan.new_text[:1000],
        "line_hint": "L1",
        "diff_preview": diff_preview,
        "diff_truncated": False,
        "changed": True,
    }
    return {
        "status": "ok",
        "action_name": "local.synthetic_create_preview",
        "kind": "action",
        "output": output,
    }


def apply_file_with_snapshot_and_validation(
    bridge: AICoreBridge,
    plan: FixPlan,
) -> Dict[str, Any]:
    """
    整文件标准化统一走：
    snapshot -> 直接写新文件 -> 本地校验 -> 失败回滚

    这样避免把整文件标准化过度耦合到 replace_text 语义，
    也能把失败原因打清楚。
    """
    snapshot = bridge.create_snapshot(
        [plan.path],
        reason=f"module_repair_playbook_v2_2:{plan.kind}:{plan.relpath}",
        metadata={"kind": plan.kind, "path": plan.path},
    )
    if not snapshot.get("ok"):
        return {
            "ok": False,
            "reason": "snapshot_failed",
            "snapshot": snapshot,
            "validation": None,
            "rollback": None,
            "write_mode": "direct_rewrite",
        }

    snapshot_id = snapshot.get("snapshot_id")
    path_obj = Path(plan.path)

    try:
        atomic_write_text(path_obj, plan.new_text, encoding="utf-8")
    except Exception as e:
        rollback = bridge.rollback_snapshot(snapshot_id) if snapshot_id else None
        return {
            "ok": False,
            "reason": f"write_failed: {e}",
            "snapshot": snapshot,
            "validation": None,
            "rollback": rollback,
            "write_mode": "direct_rewrite",
        }

    validation = run_local_validation_checks(plan.validation_checks)

    if not validation.get("ok"):
        rollback = bridge.rollback_snapshot(snapshot_id) if snapshot_id else None
        return {
            "ok": False,
            "reason": "validation_failed",
            "snapshot": snapshot,
            "validation": validation,
            "rollback": rollback,
            "write_mode": "direct_rewrite",
        }

    # 额外做一次目标文本本地验证（json / python）
    local_after = local_validate_plan(plan, safe_read_text(path_obj))
    if not local_after.get("ok"):
        rollback = bridge.rollback_snapshot(snapshot_id) if snapshot_id else None
        return {
            "ok": False,
            "reason": f"local_post_validation_failed: {local_after.get('summary')}",
            "snapshot": snapshot,
            "validation": validation,
            "local_validation": local_after,
            "rollback": rollback,
            "write_mode": "direct_rewrite",
        }

    return {
        "ok": True,
        "reason": "apply_ok",
        "snapshot": snapshot,
        "validation": validation,
        "local_validation": local_after,
        "rollback": None,
        "write_mode": "direct_rewrite",
    }


def exec_fix_plan(
    bridge: AICoreBridge,
    plan: FixPlan,
    *,
    apply: bool,
    allow_high_risk: bool = False,
) -> FixExecution:
    fx = FixExecution(
        kind=plan.kind,
        path=plan.path,
        relpath=plan.relpath,
        ok=False,
        mode="preview_only" if not apply else "apply",
    )

    # 0) 目标文本本地校验
    local_precheck = local_validate_plan(plan, plan.new_text)
    if not local_precheck.get("ok"):
        fx.mode = "failed"
        fx.reason = f"local_target_validation_failed: {local_precheck.get('summary')}"
        fx.local_validation = local_precheck
        return fx

    # 1) preview
    if not plan.file_exists_before:
        fx.preview = synthetic_preview_for_missing_file(plan)
    else:
        preview_ctx = {
            "path": plan.relpath,
            "old": plan.old_text,
            "new": plan.new_text,
        }
        preview_action = plan.preview_action
        preview_res = bridge.process_action(
            preview_action,
            runtime_context=preview_ctx,
            user_query=f"{plan.kind} preview {plan.relpath}",
        )
        fx.preview = preview_res.get("step")
        if not preview_res.get("ok"):
            fx.mode = "failed"
            fx.reason = f"preview_failed: {(fx.preview or {}).get('reason') or 'unknown'}"
            return fx

    # 2) review gate
    if plan.review_gate:
        review_res = bridge.process_action(
            "code_reviewer.review_text",
            runtime_context={"text": plan.new_text},
            user_query=f"{plan.kind} review target text",
        )
        fx.review = review_res.get("step")

        if not review_res.get("ok"):
            fx.mode = "failed"
            fx.reason = f"review_failed: {(fx.review or {}).get('reason') or 'unknown'}"
            return fx

        review_output = (fx.review or {}).get("output") or {}
        risk_level = str(review_output.get("risk_level") or "unknown")
        if risk_level == "high" and not allow_high_risk:
            fx.mode = "skipped"
            fx.reason = "review_high_risk_blocked"
            return fx

    # 3) syntax gate
    if plan.syntax_gate:
        syntax_res = bridge.process_action(
            "code_executor.syntax_check",
            runtime_context={"text": plan.new_text},
            user_query=f"{plan.kind} syntax gate",
        )
        fx.syntax = syntax_res.get("step")
        if not syntax_res.get("ok"):
            fx.mode = "failed"
            fx.reason = f"syntax_gate_failed: {(fx.syntax or {}).get('reason') or 'unknown'}"
            return fx

    # 4) 只预演
    if not apply:
        fx.mode = "preview_only"
        fx.ok = True
        fx.reason = "preview_ok"
        return fx

    # 5) 正式 apply：统一走 snapshot + direct rewrite + local validation
    apply_result = apply_file_with_snapshot_and_validation(bridge, plan)
    fx.apply = apply_result
    fx.local_validation = apply_result.get("local_validation") or apply_result.get("validation")

    if not apply_result.get("ok"):
        fx.mode = "failed"
        fx.reason = str(apply_result.get("reason") or "apply_failed")
        fx.ok = False
        return fx

    fx.mode = "apply"
    fx.ok = True
    fx.reason = "apply_ok"
    return fx


# ============================================================
# 模块扫描
# ============================================================

def discover_modules(root: Path) -> List[Path]:
    modules_dir = root / "modules"
    if not modules_dir.exists():
        return []

    out: List[Path] = []
    for child in sorted(modules_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if (child / "module.py").exists() or (child / "manifest.json").exists():
            out.append(child)
    return out


def filter_modules(modules: List[Path], selected: List[str]) -> List[Path]:
    if not selected:
        return modules
    selected_set = set(selected)
    return [m for m in modules if m.name in selected_set]


# ============================================================
# 打印
# ============================================================

def print_module_report(mod: ModuleReport, apply: bool) -> None:
    log("-" * 88)
    log(f"[{mod.module}] issues={len(mod.issues)}, fixes={len(mod.plans)}, apply={apply}")

    for issue in mod.issues:
        log(f"  ISSUE  {issue.code}: {issue.detail}")

    for exe in mod.executions:
        if exe.preview:
            step = exe.preview
            output = step.get("output") or {}
            risk = output.get("estimated_risk") or output.get("risk_level")
            line_hint = output.get("line_hint")
            log(
                f"  PREVIEW {exe.kind}: status={step.get('status')} "
                f"risk={risk} line={line_hint} reason={step.get('reason')}"
            )

        if exe.review:
            output = (exe.review or {}).get("output") or {}
            log(
                f"  REVIEW  {exe.kind}: status={(exe.review or {}).get('status')} "
                f"risk={output.get('risk_level')} issue_count={output.get('issue_count')}"
            )

        if exe.syntax:
            output = (exe.syntax or {}).get("output") or {}
            log(
                f"  SYNTAX  {exe.kind}: status={(exe.syntax or {}).get('status')} "
                f"syntax_ok={output.get('syntax_ok')}"
            )

        if exe.mode == "preview_only":
            log(f"  PREVIEW-ONLY {exe.kind}: ok={exe.ok} reason={exe.reason}")

        if exe.apply is not None:
            snapshot_id = None
            if isinstance(exe.apply, dict):
                snapshot_id = ((exe.apply.get("snapshot") or {}).get("snapshot_id"))
            log(
                f"  APPLIED {exe.kind}: ok={exe.ok} reason={exe.reason} "
                f"snapshot_id={snapshot_id} write_mode={(exe.apply or {}).get('write_mode')}"
            )

            validation = (exe.apply or {}).get("validation") or {}
            if validation:
                log(
                    f"  VALIDATE {exe.kind}: ok={validation.get('ok')} "
                    f"summary={validation.get('summary')}"
                )

            rollback = (exe.apply or {}).get("rollback") or {}
            if rollback:
                log(
                    f"  ROLLBACK {exe.kind}: ok={rollback.get('ok')} "
                    f"snapshot_id={rollback.get('snapshot_id')}"
                )

        if exe.local_validation is not None and "checks" not in (exe.local_validation or {}):
            log(
                f"  LOCAL-VALIDATE {exe.kind}: ok={exe.local_validation.get('ok')} "
                f"summary={exe.local_validation.get('summary')}"
            )

        if not exe.ok:
            log(f"  RESULT {exe.kind}: FAIL -> {exe.reason}")


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶模块修复编排器 v2.2")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="仅处理指定模块，可重复传入")
    parser.add_argument("--apply", action="store_true", help="正式落盘；默认仅预演")
    parser.add_argument("--allow-high-risk", action="store_true", help="允许高风险 review 继续 apply")
    parser.add_argument("--report-json", default="", help="报告输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    report_json = (
        Path(args.report_json).resolve()
        if args.report_json
        else (root / "audit_output" / "module_repair_playbook_v2_1_report.json")
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    log("=" * 88)
    log("module_repair_playbook v2.2 开始")
    log("=" * 88)
    log(f"root     : {root}")
    log(f"apply    : {args.apply}")
    log(f"modules  : {'ALL' if not args.module else args.module}")

    modules = filter_modules(discover_modules(root), args.module)
    log(f"selected : {len(modules)}")

    try:
        bridge = AICoreBridge(root)
        bootstrap_info = bridge.bootstrap_info
    except Exception:
        log("[ERROR] AICoreBridge init failed")
        log(traceback.format_exc())
        return 3

    module_reports: List[ModuleReport] = []
    total_issues = 0
    total_fixes = 0
    total_ok = 0
    total_fail = 0

    for module_dir in modules:
        try:
            report = analyze_module(module_dir, root)
            total_issues += len(report.issues)
            total_fixes += len(report.plans)

            for plan in report.plans:
                exe = exec_fix_plan(
                    bridge,
                    plan,
                    apply=args.apply,
                    allow_high_risk=args.allow_high_risk,
                )
                report.executions.append(exe)
                if exe.ok:
                    total_ok += 1
                else:
                    total_fail += 1

            print_module_report(report, args.apply)
            module_reports.append(report)
        except Exception:
            log("-" * 88)
            log(f"[{module_dir.name}] CRASH")
            log(traceback.format_exc())
            dummy = ModuleReport(module=module_dir.name, module_dir=str(module_dir))
            dummy.issues.append(Issue(code="PLAYBOOK_CRASH", detail=traceback.format_exc()))
            module_reports.append(dummy)
            total_fail += 1

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "apply": bool(args.apply),
        "selected_modules": [m.name for m in modules],
        "bootstrap_info": bootstrap_info,
        "summary": {
            "module_count": len(modules),
            "total_issues": total_issues,
            "total_fixes": total_fixes,
            "total_ok": total_ok,
            "total_fail": total_fail,
        },
        "modules": [m.to_dict() for m in module_reports],
    }

    report_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log()
    log("=" * 88)
    log("module_repair_playbook v2.2 完成")
    log("=" * 88)
    log(f"total_issues : {total_issues}")
    log(f"total_fixes  : {total_fixes}")
    log(f"total_ok     : {total_ok}")
    log(f"total_fail   : {total_fail}")
    log(f"report_json  : {report_json}")
    log("=" * 88)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
