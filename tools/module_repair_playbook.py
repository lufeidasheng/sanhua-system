#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ============================================================
# 数据模型
# ============================================================

@dataclass
class FixAction:
    kind: str
    file: str
    reason: str
    old_exists: bool
    changed: bool
    applied: bool
    backup: Optional[str] = None
    extra: Optional[dict] = None


@dataclass
class ModuleReport:
    module_name: str
    module_dir: str
    ok: bool
    issues: list[dict]
    fixes: list[FixAction]
    summary: str


# ============================================================
# 通用工具
# ============================================================

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def try_parse_python(text: str) -> tuple[bool, Optional[str]]:
    try:
        ast.parse(text)
        return True, None
    except SyntaxError as e:
        return False, f"{e.msg} (line={e.lineno}, offset={e.offset})"
    except Exception as e:
        return False, str(e)


def safe_json_load(path: Path) -> tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(read_text(path)), None
    except Exception as e:
        return None, str(e)


def make_backup(root: Path, file_path: Path, backup_root: Path) -> str:
    rel = file_path.relative_to(root)
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, backup_path)
    return str(backup_path)


def list_module_dirs(root: Path) -> list[Path]:
    modules_root = root / "modules"
    if not modules_root.exists():
        return []
    return sorted([p for p in modules_root.iterdir() if p.is_dir() and not p.name.startswith(".")])


# ============================================================
# AST 分析
# ============================================================

@dataclass
class ModuleAstInfo:
    ok: bool
    parse_error: Optional[str]
    top_level_funcs: list[str]
    action_funcs: list[str]
    classes: list[str]
    has_register_actions: bool
    has_entry: bool
    probable_entry_class: Optional[str]


def analyze_module_py(module_py: Path) -> ModuleAstInfo:
    if not module_py.exists():
        return ModuleAstInfo(
            ok=False,
            parse_error="module.py not found",
            top_level_funcs=[],
            action_funcs=[],
            classes=[],
            has_register_actions=False,
            has_entry=False,
            probable_entry_class=None,
        )

    text = read_text(module_py)
    try:
        tree = ast.parse(text)
    except Exception as e:
        return ModuleAstInfo(
            ok=False,
            parse_error=str(e),
            top_level_funcs=[],
            action_funcs=[],
            classes=[],
            has_register_actions=False,
            has_entry=False,
            probable_entry_class=None,
        )

    top_level_funcs: list[str] = []
    action_funcs: list[str] = []
    classes: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_level_funcs.append(node.name)
            if node.name.startswith("action_"):
                action_funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)

    probable_entry_class = None
    for cls in classes:
        if cls.endswith("Module"):
            probable_entry_class = cls
            break

    return ModuleAstInfo(
        ok=True,
        parse_error=None,
        top_level_funcs=top_level_funcs,
        action_funcs=action_funcs,
        classes=classes,
        has_register_actions="register_actions" in top_level_funcs,
        has_entry="entry" in top_level_funcs,
        probable_entry_class=probable_entry_class,
    )


# ============================================================
# __init__.py 修复
# ============================================================

def build_safe_init_py(module_name: str) -> str:
    return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
modules.{module_name} package bootstrap
自动生成的安全导出层：
- 尽量导出 entry
- 尽量导出 register_actions
- 不因缺字段导致整个包 import 失败
"""

from __future__ import annotations

entry = None
register_actions = None

try:
    from .module import entry as _entry  # type: ignore
    entry = _entry
except Exception:
    entry = None

try:
    from .module import register_actions as _register_actions  # type: ignore
    register_actions = _register_actions
except Exception:
    register_actions = None

__all__ = ["entry", "register_actions"]
'''


def should_normalize_init(init_py: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not init_py.exists():
        reasons.append("__init__.py missing")
        return True, reasons

    text = read_text(init_py)
    stripped = text.strip()

    ok, err = try_parse_python(text)
    if not ok:
        reasons.append(f"syntax_error: {err}")

    # 历史坑：文件里残留单字符、无意义内容
    if stripped in {"s", "ss", "sss"}:
        reasons.append("poisoned_init_content")

    # 历史坑：严格 from .module import entry / register_actions
    # 一旦 module.py 没这俩符号，整个包就炸
    direct_entry = "from .module import entry" in text
    direct_reg = "from .module import register_actions" in text
    has_try = "try:" in text and "except Exception" in text

    if (direct_entry or direct_reg) and not has_try:
        reasons.append("strict_import_from_module")

    return (len(reasons) > 0), reasons


# ============================================================
# register_actions 自动补丁
# ============================================================

def build_register_actions_block(module_name: str, action_funcs: list[str]) -> str:
    lines = []
    lines.append("")
    lines.append("")
    lines.append("# ============================================================")
    lines.append("# auto-generated by module_repair_playbook v1")
    lines.append("# register_actions")
    lines.append("# ============================================================")
    lines.append("")
    lines.append("def register_actions(dispatcher):")
    lines.append('    """')
    lines.append("    自动注册 module.py 中的 action_* 顶层函数。")
    lines.append('    """')
    lines.append("    if dispatcher is None:")
    lines.append('        raise ValueError("dispatcher is required")')
    lines.append("")
    lines.append("    mapping = {")

    for fn in action_funcs:
        action_name = f"{module_name}.{fn.removeprefix('action_')}"
        lines.append(f'        "{action_name}": {fn},')

    lines.append("    }")
    lines.append("")
    lines.append("    for action_name, func in mapping.items():")
    lines.append("        dispatcher.register_action(action_name, func)")
    lines.append("")
    lines.append("    return mapping")
    lines.append("")

    return "\n".join(lines)


def should_add_register_actions(ast_info: ModuleAstInfo) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not ast_info.ok:
        reasons.append("module_py_not_parseable")
        return False, reasons

    if ast_info.has_register_actions:
        reasons.append("register_actions_already_exists")
        return False, reasons

    if not ast_info.action_funcs:
        reasons.append("no_top_level_action_funcs")
        return False, reasons

    reasons.append("top_level_action_funcs_detected")
    return True, reasons


# ============================================================
# manifest 修复
# ============================================================

def normalize_manifest(
    module_name: str,
    manifest_data: dict,
    ast_info: ModuleAstInfo,
) -> tuple[bool, dict, list[str]]:
    changed = False
    reasons: list[str] = []

    expect_name = module_name
    expect_entry = f"modules.{module_name}.module"

    if manifest_data.get("name") != expect_name:
        manifest_data["name"] = expect_name
        changed = True
        reasons.append("fix:name")

    if manifest_data.get("entry") != expect_entry:
        manifest_data["entry"] = expect_entry
        changed = True
        reasons.append("fix:entry")

    if ast_info.probable_entry_class:
        expect_entry_class = f"modules.{module_name}.module.{ast_info.probable_entry_class}"
        if manifest_data.get("entry_class") != expect_entry_class:
            manifest_data["entry_class"] = expect_entry_class
            changed = True
            reasons.append("fix:entry_class")

    # 一些低风险默认字段，只在缺失时补
    defaults = {
        "version": "0.1.0",
        "enabled": True,
        "status": "active",
        "market_compatible": False,
    }
    for k, v in defaults.items():
        if k not in manifest_data:
            manifest_data[k] = v
            changed = True
            reasons.append(f"fill:{k}")

    return changed, manifest_data, reasons


# ============================================================
# 单模块处理
# ============================================================

def process_module(
    root: Path,
    module_dir: Path,
    *,
    apply: bool,
    backup_root: Path,
) -> ModuleReport:
    module_name = module_dir.name
    module_py = module_dir / "module.py"
    init_py = module_dir / "__init__.py"
    manifest_json = module_dir / "manifest.json"

    issues: list[dict] = []
    fixes: list[FixAction] = []

    ast_info = analyze_module_py(module_py)

    if not module_py.exists():
        issues.append({
            "code": "MODULE_PY_MISSING",
            "message": "module.py 缺失，v1 不自动修复",
            "target": str(module_py),
        })
        return ModuleReport(
            module_name=module_name,
            module_dir=str(module_dir),
            ok=False,
            issues=issues,
            fixes=fixes,
            summary="module.py missing",
        )

    if not ast_info.ok:
        issues.append({
            "code": "MODULE_PY_PARSE_ERROR",
            "message": ast_info.parse_error,
            "target": str(module_py),
        })

    # --------------------------------------------------------
    # fix 1: __init__.py 标准化
    # --------------------------------------------------------
    need_init_fix, init_reasons = should_normalize_init(init_py)
    if need_init_fix:
        issues.append({
            "code": "INIT_NEEDS_NORMALIZE",
            "message": ", ".join(init_reasons),
            "target": str(init_py),
        })

        new_text = build_safe_init_py(module_name)
        changed = True

        backup_path = None
        if apply:
            if init_py.exists():
                backup_path = make_backup(root, init_py, backup_root)
            else:
                init_py.parent.mkdir(parents=True, exist_ok=True)
            write_text(init_py, new_text)

        fixes.append(FixAction(
            kind="normalize_init",
            file=str(init_py),
            reason=", ".join(init_reasons),
            old_exists=init_py.exists(),
            changed=changed,
            applied=apply,
            backup=backup_path,
            extra=None,
        ))

    # --------------------------------------------------------
    # fix 2: register_actions 自动补丁
    # --------------------------------------------------------
    need_reg_fix, reg_reasons = should_add_register_actions(ast_info)
    if need_reg_fix:
        issues.append({
            "code": "REGISTER_ACTIONS_MISSING",
            "message": ", ".join(reg_reasons),
            "target": str(module_py),
        })

        old_text = read_text(module_py)
        block = build_register_actions_block(module_name, ast_info.action_funcs)
        new_text = old_text.rstrip() + block + "\n"

        backup_path = None
        if apply:
            backup_path = make_backup(root, module_py, backup_root)
            write_text(module_py, new_text)

        fixes.append(FixAction(
            kind="append_register_actions",
            file=str(module_py),
            reason=", ".join(reg_reasons),
            old_exists=True,
            changed=True,
            applied=apply,
            backup=backup_path,
            extra={
                "action_funcs": ast_info.action_funcs,
                "action_names": [f"{module_name}.{x.removeprefix('action_')}" for x in ast_info.action_funcs],
            },
        ))

    # --------------------------------------------------------
    # fix 3: manifest.json 关键字段规范化（仅 manifest 已存在时）
    # --------------------------------------------------------
    if manifest_json.exists():
        data, err = safe_json_load(manifest_json)
        if err:
            issues.append({
                "code": "MANIFEST_JSON_PARSE_ERROR",
                "message": err,
                "target": str(manifest_json),
            })
        else:
            changed, new_data, manifest_reasons = normalize_manifest(module_name, data, ast_info)
            if changed:
                issues.append({
                    "code": "MANIFEST_NEEDS_NORMALIZE",
                    "message": ", ".join(manifest_reasons),
                    "target": str(manifest_json),
                })

                backup_path = None
                if apply:
                    backup_path = make_backup(root, manifest_json, backup_root)
                    write_text(
                        manifest_json,
                        json.dumps(new_data, ensure_ascii=False, indent=2) + "\n",
                    )

                fixes.append(FixAction(
                    kind="normalize_manifest",
                    file=str(manifest_json),
                    reason=", ".join(manifest_reasons),
                    old_exists=True,
                    changed=True,
                    applied=apply,
                    backup=backup_path,
                    extra={
                        "entry_class": new_data.get("entry_class"),
                        "entry": new_data.get("entry"),
                    },
                ))

    ok = True
    if any(i["code"] == "MODULE_PY_PARSE_ERROR" for i in issues):
        ok = False

    if not issues:
        summary = "clean"
    else:
        summary = f"issues={len(issues)}, fixes={len(fixes)}, apply={apply}"

    return ModuleReport(
        module_name=module_name,
        module_dir=str(module_dir),
        ok=ok,
        issues=issues,
        fixes=fixes,
        summary=summary,
    )


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶模块修复剧本 v1")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写盘。默认仅 dry-run 分析，不改文件。",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="只处理指定模块名，可多次传入，如 --module system_monitor --module code_reader",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"[ERROR] root 不存在: {root}")
        return 1

    backup_root = root / "audit_output" / "fix_backups" / now_ts()
    report_path = root / "audit_output" / "module_repair_playbook_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    module_dirs = list_module_dirs(root)
    if args.module:
        wanted = set(args.module)
        module_dirs = [p for p in module_dirs if p.name in wanted]

    if not module_dirs:
        print("[INFO] 未找到可处理模块")
        return 0

    reports: list[ModuleReport] = []
    total_issues = 0
    total_fixes = 0

    print("=" * 88)
    print("module_repair_playbook v1 开始")
    print("=" * 88)
    print(f"root     : {root}")
    print(f"apply    : {args.apply}")
    print(f"modules  : {len(module_dirs)}")
    print()

    for module_dir in module_dirs:
        report = process_module(
            root,
            module_dir,
            apply=args.apply,
            backup_root=backup_root,
        )
        reports.append(report)
        total_issues += len(report.issues)
        total_fixes += len(report.fixes)

        print("-" * 88)
        print(f"[{report.module_name}] {report.summary}")
        if report.issues:
            for item in report.issues:
                print(f"  ISSUE  {item['code']}: {item['message']}")
        if report.fixes:
            for fx in report.fixes:
                flag = "APPLIED" if fx.applied else "PLAN"
                print(f"  {flag:<7} {fx.kind}: {fx.file}")
        if not report.issues:
            print("  CLEAN")

    json_report = {
        "root": str(root),
        "apply": args.apply,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "module_count": len(module_dirs),
        "total_issues": total_issues,
        "total_fixes": total_fixes,
        "reports": [
            {
                "module_name": r.module_name,
                "module_dir": r.module_dir,
                "ok": r.ok,
                "issues": r.issues,
                "fixes": [asdict(fx) for fx in r.fixes],
                "summary": r.summary,
            }
            for r in reports
        ],
    }
    write_text(report_path, json.dumps(json_report, ensure_ascii=False, indent=2) + "\n")

    print()
    print("=" * 88)
    print("module_repair_playbook v1 完成")
    print("=" * 88)
    print(f"total_issues : {total_issues}")
    print(f"total_fixes  : {total_fixes}")
    print(f"report_json  : {report_path}")
    if args.apply:
        print(f"backup_root  : {backup_root}")
    print("=" * 88)

    return 0


if __name__ == "__main__":
    sys.exit(main())
