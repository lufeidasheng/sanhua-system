#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tools/module_repair_playbook_v2.py

目标：
1. 扫描 modules/ 下模块包装层问题
2. 只做“可确定、低风险、可回滚”的修复
3. 优先修：
   - __init__.py 包装层标准化
   - manifest.json 的 name / entry / entry_class / status / market_compatible
4. 通过 AICore 安全栈完成：
   - preview
   - review
   - syntax gate
   - apply
   - validate
   - rollback

适用前提：
- core/aicore/aicore.py 已具备：
  - get_aicore_instance()
  - process_suggestion_chain(...)
  - safe_apply_change_set(...)
  - _bootstrap_action_registry(...)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import traceback
from dataclasses import dataclass, asdict, field
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
    kind: str                      # init / manifest
    path: str
    relpath: str
    reason: str
    old_text: str
    new_text: str
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
    mode: str                      # preview_only / apply / skipped / failed
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

def eprint(*args, **kwargs) -> None:
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

    # 第一优先：显式继承 BaseModule
    for name, bases in classes:
        if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
            return name

    # 第二优先：名字像模块类
    for name, _ in classes:
        if name.endswith("Module"):
            return name

    # 第三优先：第一个类
    if classes:
        return classes[0][0]

    return fallback


def choose_text_contains_needle(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return fallback[:200]


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

    def rollback_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        return self.aicore.rollback_snapshot(snapshot_id)

    def resolve_dispatcher(self) -> Any:
        resolver = getattr(self.aicore, "_resolve_dispatcher", None)
        if callable(resolver):
            try:
                return resolver()
            except Exception:
                return None
        return None


# ============================================================
# 模块分析
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
                preview_action="code_inserter.preview_replace_text",
                syntax_gate=True,
                review_gate=True,
                validation_checks=[
                    {"kind": "file_exists", "target": str(init_py)},
                    {
                        "kind": "text_contains",
                        "target": str(init_py),
                        "needle": "_module = _import_module",
                    },
                    {"kind": "syntax_file", "target": str(init_py)},
                ],
                extra={"file_type": "python"},
            )
        )

    # ---------- manifest ----------
    manifest_data, manifest_error = safe_json_load(manifest_json)
    if manifest_error is not None and manifest_data is None:
        report.issues.append(Issue(code="MANIFEST_INVALID_JSON", detail=manifest_error))
    else:
        manifest_current = manifest_data or {}
        class_name = discover_module_class_name(module_name, module_py)
        entry_class = f"modules.{module_name}.module.{class_name}"
        manifest_target_obj, manifest_changes = build_normalized_manifest(
            manifest_current,
            module_name,
            entry_class,
        )
        manifest_target_text = write_json_text(manifest_target_obj)
        manifest_current_text = write_json_text(manifest_current) if manifest_current else (
            safe_read_text(manifest_json) if manifest_json.exists() else ""
        )

        if manifest_changes:
            report.issues.append(
                Issue(
                    code="MANIFEST_NEEDS_NORMALIZE",
                    detail=", ".join(manifest_changes),
                )
            )
            needle = f"\"entry_class\": \"{entry_class}\""
            report.plans.append(
                FixPlan(
                    kind="normalize_manifest",
                    path=str(manifest_json),
                    relpath=relpath_posix(manifest_json, root),
                    reason=", ".join(manifest_changes),
                    old_text=manifest_current_text,
                    new_text=manifest_target_text,
                    preview_action="code_inserter.preview_replace_text",
                    syntax_gate=False,
                    review_gate=False,
                    validation_checks=[
                        {"kind": "file_exists", "target": str(manifest_json)},
                        {"kind": "text_contains", "target": str(manifest_json), "needle": needle},
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


def build_apply_operation(plan: FixPlan) -> Dict[str, Any]:
    # 优先 replace_text；如果旧文本为空，则退化为 append_text
    if plan.old_text:
        return {
            "op": "replace_text",
            "path": plan.path,
            "old": plan.old_text,
            "new": plan.new_text,
            "occurrence": 1,
        }
    return {
        "op": "append_text",
        "path": plan.path,
        "text": plan.new_text,
    }


def extract_risk_level(review_step: Optional[Dict[str, Any]]) -> str:
    if not review_step:
        return "unknown"
    output = review_step.get("output") or {}
    return str(output.get("risk_level") or "unknown")


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

    path_rel = plan.relpath

    # 0) 本地目标内容预校验
    local_precheck = local_validate_plan(plan, plan.new_text)
    if not local_precheck.get("ok"):
        fx.mode = "failed"
        fx.reason = f"local_target_validation_failed: {local_precheck.get('summary')}"
        fx.local_validation = local_precheck
        return fx

    # 1) preview
    preview_ctx = {
        "path": path_rel,
        "old": plan.old_text,
        "new": plan.new_text,
    }
    if not plan.old_text:
        # 缺失文件时，replace_text 无法工作，退化成 append_text 预演
        if plan.preview_action.endswith("preview_replace_text"):
            preview_action = "code_inserter.preview_append_text"
            preview_ctx = {"path": path_rel, "text": plan.new_text}
        else:
            preview_action = plan.preview_action
    else:
        preview_action = plan.preview_action

    preview_res = bridge.process_action(
        preview_action,
        runtime_context=preview_ctx,
        user_query=f"{plan.kind} preview {path_rel}",
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
        review_ok = review_res.get("ok")
        risk_level = extract_risk_level(fx.review)

        if not review_ok:
            fx.mode = "failed"
            fx.reason = f"review_failed: {(fx.review or {}).get('reason') or 'unknown'}"
            return fx

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

    # 4) 仅预演
    if not apply:
        fx.mode = "preview_only"
        fx.ok = True
        fx.reason = "preview_ok"
        return fx

    # 5) 正式 apply
    operation = build_apply_operation(plan)
    apply_result = bridge.safe_apply(
        [operation],
        reason=f"module_repair_playbook_v2:{plan.kind}:{plan.relpath}",
        metadata={"kind": plan.kind, "path": plan.path},
        validation_checks=plan.validation_checks,
        dry_run=False,
    )
    fx.apply = apply_result

    if not apply_result.get("ok"):
        fx.mode = "failed"
        fx.reason = "apply_or_validation_failed"
        fx.ok = False
        return fx

    # 6) 额外本地验证（尤其 JSON）
    try:
        current_after = safe_read_text(Path(plan.path))
        local_after = local_validate_plan(plan, current_after)
        fx.local_validation = local_after
        if not local_after.get("ok"):
            snapshot_id = (((apply_result.get("apply") or {}).get("snapshot_id")))
            rollback_res = None
            if snapshot_id:
                rollback_res = bridge.rollback_snapshot(snapshot_id)
            fx.apply = {
                **apply_result,
                "post_local_rollback": rollback_res,
            }
            fx.mode = "failed"
            fx.reason = f"local_post_validation_failed: {local_after.get('summary')}"
            fx.ok = False
            return fx
    except Exception as e:
        fx.local_validation = {"ok": False, "summary": str(e)}
        fx.mode = "failed"
        fx.reason = f"local_post_validation_exception: {e}"
        fx.ok = False
        return fx

    fx.mode = "apply"
    fx.ok = True
    fx.reason = "apply_ok"
    return fx


# ============================================================
# 扫描 / 过滤
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
    eprint("-" * 88)
    eprint(f"[{mod.module}] issues={len(mod.issues)}, fixes={len(mod.plans)}, apply={apply}")

    for issue in mod.issues:
        eprint(f"  ISSUE  {issue.code}: {issue.detail}")

    for exe in mod.executions:
        if exe.preview:
            step = exe.preview
            output = step.get("output") or {}
            risk = output.get("estimated_risk") or output.get("risk_level")
            line_hint = output.get("line_hint")
            eprint(
                f"  PREVIEW {exe.kind}: status={step.get('status')} "
                f"risk={risk} line={line_hint} reason={step.get('reason')}"
            )

        if exe.review:
            output = (exe.review or {}).get("output") or {}
            eprint(
                f"  REVIEW  {exe.kind}: status={(exe.review or {}).get('status')} "
                f"risk={output.get('risk_level')} issue_count={output.get('issue_count')}"
            )

        if exe.syntax:
            output = (exe.syntax or {}).get("output") or {}
            eprint(
                f"  SYNTAX  {exe.kind}: status={(exe.syntax or {}).get('status')} "
                f"syntax_ok={output.get('syntax_ok')}"
            )

        if exe.mode == "preview_only":
            eprint(f"  PREVIEW-ONLY {exe.kind}: ok={exe.ok} reason={exe.reason}")

        if exe.apply is not None:
            apply_block = exe.apply.get("apply") if isinstance(exe.apply, dict) else None
            snapshot_id = (apply_block or {}).get("snapshot_id") if isinstance(apply_block, dict) else None
            eprint(
                f"  APPLIED {exe.kind}: ok={exe.ok} reason={exe.reason} "
                f"snapshot_id={snapshot_id}"
            )

        if exe.local_validation is not None:
            eprint(
                f"  LOCAL-VALIDATE {exe.kind}: ok={exe.local_validation.get('ok')} "
                f"summary={exe.local_validation.get('summary')}"
            )

        if not exe.ok:
            eprint(f"  RESULT {exe.kind}: FAIL -> {exe.reason}")


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶模块修复编排器 v2")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="仅处理指定模块，可重复传入")
    parser.add_argument("--apply", action="store_true", help="正式落盘；默认仅预演")
    parser.add_argument(
        "--allow-high-risk",
        action="store_true",
        help="允许 review_text 返回 high risk 时继续 apply（默认阻断）",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="报告输出路径，默认写到 audit_output/module_repair_playbook_v2_report.json",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        eprint(f"[ERROR] root not found: {root}")
        return 2

    report_json = (
        Path(args.report_json).resolve()
        if args.report_json
        else (root / "audit_output" / "module_repair_playbook_v2_report.json")
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    eprint("=" * 88)
    eprint("module_repair_playbook v2 开始")
    eprint("=" * 88)
    eprint(f"root     : {root}")
    eprint(f"apply    : {args.apply}")
    eprint(f"modules  : {len(args.module) if args.module else 'ALL'}")

    modules = filter_modules(discover_modules(root), args.module)
    eprint(f"selected : {len(modules)}")

    bridge = None
    bootstrap_info = None
    try:
        bridge = AICoreBridge(root)
        bootstrap_info = bridge.bootstrap_info
    except Exception as e:
        eprint("[ERROR] AICoreBridge init failed")
        eprint(traceback.format_exc())
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
            eprint("-" * 88)
            eprint(f"[{module_dir.name}] CRASH")
            eprint(traceback.format_exc())
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

    eprint()
    eprint("=" * 88)
    eprint("module_repair_playbook v2 完成")
    eprint("=" * 88)
    eprint(f"total_issues : {total_issues}")
    eprint(f"total_fixes  : {total_fixes}")
    eprint(f"total_ok     : {total_ok}")
    eprint(f"total_fail   : {total_fail}")
    eprint(f"report_json  : {report_json}")
    eprint("=" * 88)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
