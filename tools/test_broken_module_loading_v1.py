#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_TARGET_MODULES = [
    "model_engine_actions",
    "state_describe",
]


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CaseResult:
    module: str
    ast_base_subclasses: List[str] = field(default_factory=list)
    entry_class: str = ""
    issubclass: bool = False
    instantiate_ok: Optional[bool] = None
    setup_ok: Optional[bool] = None
    preload_ok: Optional[bool] = None
    health_ok: Optional[bool] = None
    missing_actions: Optional[List[str]] = None
    smoke_action: Optional[str] = None
    smoke_status: Optional[str] = None
    smoke_source: Optional[str] = None
    smoke_view: Optional[str] = None
    smoke_reason: Optional[str] = None
    ok: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 基础工具
# ============================================================

def log(*args, **kwargs) -> None:
    print(*args, **kwargs)


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


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
        return {}, "json_not_dict"
    except Exception as e:
        return None, str(e)


def extract_base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def discover_base_subclasses(module_py: Path) -> List[str]:
    text = safe_read_text(module_py)
    if not text:
        return []
    try:
        tree = ast.parse(text, filename=str(module_py))
    except Exception:
        return []
    out: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [extract_base_name(b) for b in node.bases]
            if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
                out.append(node.name)
    return out


def import_from_path(dotted: str):
    module_name, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, attr)


def safe_call(fn, *args, **kwargs):
    if not callable(fn):
        return None
    last_error = None
    trials = [
        lambda: fn(*args, **kwargs),
        lambda: fn(*args),
        lambda: fn(),
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


def status_line(step: Dict[str, Any]) -> str:
    if not step:
        return "action=None status=None source=None view=None reason=None"
    output = step.get("output") or {}
    return (
        f"action={step.get('action_name')} "
        f"status={step.get('status')} "
        f"source={output.get('source')} "
        f"view={output.get('view')} "
        f"reason={step.get('reason')}"
    )


# ============================================================
# AICore 桥
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
            self.bootstrap_info = self.aicore._bootstrap_action_registry(force=True)

    def resolve_dispatcher(self):
        resolver = getattr(self.aicore, "_resolve_dispatcher", None)
        if callable(resolver):
            try:
                return resolver()
            except Exception:
                return None
        return None

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


# ============================================================
# 测试逻辑
# ============================================================

def extract_declared_actions(manifest_obj: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for item in manifest_obj.get("actions", []) or []:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                out.append(str(name))
        elif isinstance(item, str):
            out.append(item)
    return out


def choose_smoke_action(module_name: str, declared_actions: List[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    preferred = {
        "model_engine_actions": None,
        "state_describe": None,
    }
    if preferred.get(module_name):
        return preferred[module_name], {}

    if declared_actions:
        return declared_actions[0], {}

    return None, {}


def instantiate_module(entry_cls, dispatcher):
    trials = [
        lambda: entry_cls(dispatcher=dispatcher, context={"dispatcher": dispatcher}),
        lambda: entry_cls(context={"dispatcher": dispatcher}),
        lambda: entry_cls(dispatcher=dispatcher),
        lambda: entry_cls(),
    ]
    last_error = None
    for build in trials:
        try:
            return build()
        except TypeError as e:
            last_error = e
            continue
    if last_error is not None:
        raise last_error
    return entry_cls()


def test_single_module(
    root: Path,
    bridge: AICoreBridge,
    base_module_cls: type,
    module_name: str,
) -> CaseResult:
    module_dir = root / "modules" / module_name
    module_py = module_dir / "module.py"
    manifest_json = module_dir / "manifest.json"

    case = CaseResult(module=module_name)

    manifest_obj, manifest_error = safe_json_load(manifest_json)
    if manifest_error is not None and manifest_obj is None:
        case.reason = f"manifest_invalid: {manifest_error}"
        return case

    manifest_obj = manifest_obj or {}
    case.entry_class = str(manifest_obj.get("entry_class") or "")

    case.ast_base_subclasses = discover_base_subclasses(module_py)

    if not case.entry_class:
        case.reason = "manifest.entry_class missing"
        return case

    try:
        entry_cls = import_from_path(case.entry_class)
    except Exception as e:
        case.reason = f"导入 entry_class 失败: {e}"
        return case

    try:
        case.issubclass = issubclass(entry_cls, base_module_cls)
    except Exception:
        case.issubclass = False

    if not case.issubclass:
        case.reason = f"{case.entry_class} 不是 BaseModule 子类"
        return case

    dispatcher = bridge.resolve_dispatcher()

    try:
        instance = instantiate_module(entry_cls, dispatcher)
        case.instantiate_ok = True
    except Exception as e:
        case.instantiate_ok = False
        case.reason = f"实例化失败: {e}"
        return case

    try:
        if hasattr(instance, "preload"):
            safe_call(getattr(instance, "preload"))
        case.preload_ok = True
    except Exception as e:
        case.preload_ok = False
        case.reason = f"preload 失败: {e}"
        return case

    try:
        if hasattr(instance, "setup"):
            safe_call(getattr(instance, "setup"))
        case.setup_ok = True
    except Exception as e:
        case.setup_ok = False
        case.reason = f"setup 失败: {e}"
        return case

    try:
        hc = safe_call(getattr(instance, "health_check", None))
        if isinstance(hc, dict):
            case.health_ok = bool(hc.get("ok", True))
        else:
            case.health_ok = True
    except Exception as e:
        case.health_ok = False
        case.reason = f"health_check 失败: {e}"
        return case

    declared_actions = extract_declared_actions(manifest_obj)
    missing: List[str] = []
    if dispatcher is not None and hasattr(dispatcher, "get_action"):
        for name in declared_actions:
            try:
                if dispatcher.get_action(name) is None:
                    missing.append(name)
            except Exception:
                missing.append(name)
    case.missing_actions = missing

    smoke_action, smoke_ctx = choose_smoke_action(module_name, declared_actions)
    case.smoke_action = smoke_action

    # 这两个模块当前不强制 smoke action
    if smoke_action:
        smoke = bridge.process_action(
            smoke_action,
            runtime_context=smoke_ctx,
            user_query=f"test_{module_name}_smoke",
        )
        step = smoke.get("step") or {}
        out = step.get("output") or {}
        case.smoke_status = step.get("status")
        case.smoke_source = out.get("source")
        case.smoke_view = out.get("view")
        case.smoke_reason = step.get("reason")
        if not smoke.get("ok"):
            case.reason = f"smoke failed: {case.smoke_reason or 'unknown'}"
            return case

    case.ok = True
    case.reason = "ok"
    return case


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="测试 broken modules official 化后的加载状态")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="指定模块，可重复")
    parser.add_argument("--report-json", default="", help="报告输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    ensure_sys_path(root)

    selected_modules = args.module or DEFAULT_TARGET_MODULES
    report_json = (
        Path(args.report_json).resolve()
        if args.report_json
        else root / "audit_output" / "test_broken_module_loading_v1_report.json"
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    try:
        base_module_cls = import_from_path("core.core2_0.sanhuatongyu.module.base.BaseModule")
    except Exception:
        log("[ERROR] BaseModule 导入失败")
        log(traceback.format_exc())
        return 3

    try:
        bridge = AICoreBridge(root)
    except Exception:
        log("[ERROR] AICoreBridge 初始化失败")
        log(traceback.format_exc())
        return 4

    log("=" * 100)
    log("TEST BROKEN MODULE LOADING V1")
    log("=" * 100)
    log(f"root               : {root}")
    log("base_module_import : core.core2_0.sanhuatongyu.module.base.BaseModule")
    log(f"selected_modules   : {selected_modules}")
    log(f"bootstrap_info     : {bridge.bootstrap_info}")

    results: List[CaseResult] = []
    total_ok = 0
    total_fail = 0

    for module_name in selected_modules:
        log("-" * 100)
        log(f"[CASE] {module_name}")
        try:
            case = test_single_module(
                root=root,
                bridge=bridge,
                base_module_cls=base_module_cls,
                module_name=module_name,
            )
        except Exception:
            tb = traceback.format_exc()
            case = CaseResult(
                module=module_name,
                ok=False,
                reason=f"crash: {tb}",
            )

        results.append(case)

        log(f"  ast_base_subclasses : {case.ast_base_subclasses}")
        log(f"  entry_class         : {case.entry_class}")
        log(f"  issubclass          : {case.issubclass}")
        log(f"  instantiate_ok      : {case.instantiate_ok}")
        log(f"  preload_ok          : {case.preload_ok}")
        log(f"  setup_ok            : {case.setup_ok}")
        log(f"  health_ok           : {case.health_ok}")
        log(f"  missing_actions     : {case.missing_actions}")
        log(
            "  smoke               : "
            f"action={case.smoke_action} "
            f"status={case.smoke_status} "
            f"source={case.smoke_source} "
            f"view={case.smoke_view} "
            f"reason={case.smoke_reason}"
        )
        log(f"  RESULT              : {'PASS' if case.ok else 'FAIL'} ({case.reason})")

        if case.ok:
            total_ok += 1
        else:
            total_fail += 1

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "selected_modules": selected_modules,
        "bootstrap_info": bridge.bootstrap_info,
        "summary": {
            "total_ok": total_ok,
            "total_fail": total_fail,
        },
        "cases": [r.to_dict() for r in results],
    }
    report_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log()
    log("=" * 100)
    log("TEST BROKEN MODULE LOADING V1 DONE")
    log("=" * 100)
    log(f"total_ok    : {total_ok}")
    log(f"total_fail  : {total_fail}")
    log(f"report_json : {report_json}")
    log("=" * 100)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
