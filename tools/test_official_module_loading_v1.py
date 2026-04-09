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
    "code_executor",
    "code_inserter",
    "code_reader",
    "code_reviewer",
    "system_control",
    "system_monitor",
]

EXPECTED_ACTIONS: Dict[str, List[str]] = {
    "code_executor": [
        "code_executor.syntax_check",
        "code_executor.syntax_file",
    ],
    "code_inserter": [
        "code_inserter.preview_replace_text",
        "code_inserter.preview_append_text",
    ],
    "code_reader": [
        "code_reader.exists",
        "code_reader.read_file",
        "code_reader.list_dir",
    ],
    "code_reviewer": [
        "code_reviewer.review_text",
        "code_reviewer.review_file",
    ],
    "system_control": [
        "system.health_check",
        "system.status",
    ],
    "system_monitor": [
        "sysmon.health",
        "sysmon.metrics",
        "sysmon.status",
    ],
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CaseResult:
    module: str
    ok: bool
    checks: Dict[str, Any] = field(default_factory=dict)
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
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_json_load(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        obj = json.loads(safe_read_text(path))
        if isinstance(obj, dict):
            return obj, None
        return {}, "manifest_not_dict"
    except Exception as e:
        return {}, str(e)


def rel_module_import(py_file: Path, root: Path) -> str:
    rel = py_file.resolve().relative_to(root.resolve())
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def extract_base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def parse_classes(py_text: str, filename: str = "<string>") -> List[Tuple[str, List[str]]]:
    try:
        tree = ast.parse(py_text, filename=filename)
    except Exception:
        return []
    out: List[Tuple[str, List[str]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [extract_base_name(b) for b in node.bases]
            out.append((node.name, bases))
    return out


def find_base_subclasses(py_text: str, filename: str = "<string>") -> List[str]:
    out = []
    for cls_name, bases in parse_classes(py_text, filename=filename):
        for base in bases:
            if base == "BaseModule" or base.endswith(".BaseModule") or base.endswith("BaseModule"):
                out.append(cls_name)
                break
    return out


def find_base_module_import(root: Path) -> str:
    candidates: List[str] = []
    for py in root.rglob("*.py"):
        try:
            text = safe_read_text(py)
            if "class BaseModule" not in text:
                continue
            tree = ast.parse(text, filename=str(py))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == "BaseModule":
                    candidates.append(rel_module_import(py, root))
                    break
        except Exception:
            continue

    preferred = [
        "core.core2_0.sanhuatongyu.module.base",
        "core.core2_0.sanhuatongyu.module.base_module",
    ]
    for item in preferred:
        if item in candidates:
            return item
    if not candidates:
        raise RuntimeError("未找到 BaseModule import path")
    return sorted(candidates, key=lambda x: (0 if x.endswith(".base") else 1, len(x), x))[0]


def build_smoke_runtime_context(module_name: str) -> Tuple[str, Dict[str, Any]]:
    if module_name == "code_executor":
        return "code_executor.syntax_check", {
            "text": "def demo():\n    return 1\n",
        }
    if module_name == "code_inserter":
        return "code_inserter.preview_replace_text", {
            "path": "config/global.yaml",
            "old": "modules: {}",
            "new": "modules:\n  demo: true",
        }
    if module_name == "code_reader":
        return "code_reader.read_file", {
            "path": "config/global.yaml",
            "max_chars": 1200,
        }
    if module_name == "code_reviewer":
        return "code_reviewer.review_text", {
            "text": "def demo():\n    value = 1\n    return value\n",
            "max_chars": 2000,
        }
    if module_name == "system_control":
        return "system.status", {}
    if module_name == "system_monitor":
        return "sysmon.status", {}
    raise KeyError(module_name)


# ============================================================
# 主测试
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="测试 legacy 模块是否已 official 化并可被加载")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="指定模块，可重复")
    parser.add_argument("--report-json", default="", help="报告输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    ensure_sys_path(root)
    os.chdir(root)

    report_json = Path(args.report_json).resolve() if args.report_json else (root / "audit_output" / "test_official_module_loading_v1_report.json")
    report_json.parent.mkdir(parents=True, exist_ok=True)

    selected_modules = args.module or list(DEFAULT_TARGET_MODULES)

    try:
        base_module_import = find_base_module_import(root)
        base_mod = importlib.import_module(base_module_import)
        BaseModule = getattr(base_mod, "BaseModule")
    except Exception as e:
        log(f"[ERROR] BaseModule 加载失败: {e}")
        return 3

    try:
        from core.aicore.aicore import get_aicore_instance
        aicore = get_aicore_instance()
        bootstrap_info = None
        if hasattr(aicore, "_bootstrap_action_registry"):
            try:
                bootstrap_info = aicore._bootstrap_action_registry(force=True)
            except Exception as e:
                bootstrap_info = {"ok": False, "reason": str(e)}
        dispatcher = aicore._resolve_dispatcher() if hasattr(aicore, "_resolve_dispatcher") else None
    except Exception as e:
        log(f"[ERROR] AICore 初始化失败: {e}")
        log(traceback.format_exc())
        return 4

    log("=" * 100)
    log("TEST OFFICIAL MODULE LOADING V1")
    log("=" * 100)
    log(f"root               : {root}")
    log(f"base_module_import : {base_module_import}")
    log(f"selected_modules   : {selected_modules}")
    log(f"bootstrap_info     : {bootstrap_info}")

    results: List[CaseResult] = []

    for module_name in selected_modules:
        log("-" * 100)
        log(f"[CASE] {module_name}")

        case = CaseResult(module=module_name, ok=False)
        try:
            module_dir = root / "modules" / module_name
            module_py = module_dir / "module.py"
            manifest_json = module_dir / "manifest.json"

            manifest_obj, manifest_err = safe_json_load(manifest_json)
            if manifest_err:
                raise RuntimeError(f"manifest 读取失败: {manifest_err}")

            module_text = safe_read_text(module_py)
            ast_base_subclasses = find_base_subclasses(module_text, filename=str(module_py))
            case.checks["ast_base_subclasses"] = ast_base_subclasses
            case.checks["ast_base_subclass_count"] = len(ast_base_subclasses)

            entry_class = manifest_obj.get("entry_class", "")
            case.checks["manifest_entry_class"] = entry_class
            if not entry_class or not isinstance(entry_class, str):
                raise RuntimeError("manifest.entry_class 缺失")

            import_path, class_name = entry_class.rsplit(".", 1)
            imported_mod = importlib.import_module(import_path)
            cls = getattr(imported_mod, class_name, None)
            case.checks["entry_class_import_ok"] = cls is not None
            if cls is None:
                raise RuntimeError(f"entry_class 导入后不存在: {entry_class}")

            case.checks["issubclass_BaseModule"] = bool(isinstance(cls, type) and issubclass(cls, BaseModule))
            if not case.checks["issubclass_BaseModule"]:
                raise RuntimeError(f"{entry_class} 不是 BaseModule 子类")

            # 实例化
            instance = None
            ctor_ok = False
            ctor_reason = ""
            for ctor in (
                lambda: cls(),
                lambda: cls(context={"dispatcher": dispatcher}),
                lambda: cls(dispatcher=dispatcher),
            ):
                try:
                    instance = ctor()
                    ctor_ok = True
                    break
                except Exception as e:
                    ctor_reason = str(e)
            case.checks["instantiate_ok"] = ctor_ok
            case.checks["instantiate_reason"] = ctor_reason
            if not ctor_ok:
                raise RuntimeError(f"实例化失败: {ctor_reason}")

            # setup
            setup_ok = True
            setup_reason = ""
            setup_result = None
            if hasattr(instance, "setup"):
                try:
                    setup_result = instance.setup(context={"dispatcher": dispatcher})
                except TypeError:
                    try:
                        setup_result = instance.setup({"dispatcher": dispatcher})
                    except Exception as e:
                        setup_ok = False
                        setup_reason = str(e)
                except Exception as e:
                    setup_ok = False
                    setup_reason = str(e)
            case.checks["setup_ok"] = setup_ok
            case.checks["setup_reason"] = setup_reason
            case.checks["setup_result"] = setup_result
            if not setup_ok:
                raise RuntimeError(f"setup 失败: {setup_reason}")

            # 官方动作 presence
            expected_actions = EXPECTED_ACTIONS.get(module_name, [])
            action_presence = {}
            for action_name in expected_actions:
                action_presence[action_name] = bool(dispatcher.get_action(action_name)) if dispatcher and hasattr(dispatcher, "get_action") else False
            case.checks["expected_actions"] = expected_actions
            case.checks["action_presence"] = action_presence

            missing = [k for k, v in action_presence.items() if not v]
            case.checks["missing_actions"] = missing
            if missing:
                raise RuntimeError(f"缺失动作: {missing}")

            # smoke
            smoke_action, smoke_ctx = build_smoke_runtime_context(module_name)
            smoke = aicore.process_suggestion_chain(
                f"1. 调用 {smoke_action} 执行动作",
                user_query=f"official_module_smoke:{module_name}",
                runtime_context=smoke_ctx,
                dry_run=False,
            )
            step_results = ((smoke.get("execution") or {}).get("step_results") or [])
            first_step = step_results[0] if step_results else {}
            case.checks["smoke_action"] = smoke_action
            case.checks["smoke_status"] = first_step.get("status")
            case.checks["smoke_reason"] = first_step.get("reason")
            case.checks["smoke_source"] = (first_step.get("output") or {}).get("source") if isinstance(first_step.get("output"), dict) else None
            case.checks["smoke_view"] = (first_step.get("output") or {}).get("view") if isinstance(first_step.get("output"), dict) else None

            if first_step.get("status") != "ok":
                raise RuntimeError(f"smoke 失败: {first_step.get('reason')}")

            case.ok = True
            case.reason = "ok"

        except Exception as e:
            case.ok = False
            case.reason = str(e)
            case.checks["traceback"] = traceback.format_exc()

        results.append(case)

        log(f"  ast_base_subclasses : {case.checks.get('ast_base_subclasses')}")
        log(f"  entry_class         : {case.checks.get('manifest_entry_class')}")
        log(f"  issubclass          : {case.checks.get('issubclass_BaseModule')}")
        log(f"  instantiate_ok      : {case.checks.get('instantiate_ok')}")
        log(f"  setup_ok            : {case.checks.get('setup_ok')}")
        log(f"  missing_actions     : {case.checks.get('missing_actions')}")
        log(
            f"  smoke               : action={case.checks.get('smoke_action')} "
            f"status={case.checks.get('smoke_status')} "
            f"source={case.checks.get('smoke_source')} "
            f"view={case.checks.get('smoke_view')} "
            f"reason={case.checks.get('smoke_reason')}"
        )
        log(f"  RESULT              : {'PASS' if case.ok else 'FAIL'} ({case.reason})")

    total_ok = sum(1 for x in results if x.ok)
    total_fail = sum(1 for x in results if not x.ok)

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "base_module_import": base_module_import,
        "selected_modules": selected_modules,
        "bootstrap_info": bootstrap_info,
        "results": [x.to_dict() for x in results],
        "summary": {
            "total_modules": len(selected_modules),
            "total_ok": total_ok,
            "total_fail": total_fail,
        },
    }
    report_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log()
    log("=" * 100)
    log("TEST OFFICIAL MODULE LOADING V1 DONE")
    log("=" * 100)
    log(f"total_ok    : {total_ok}")
    log(f"total_fail  : {total_fail}")
    log(f"report_json : {report_json}")
    log("=" * 100)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
