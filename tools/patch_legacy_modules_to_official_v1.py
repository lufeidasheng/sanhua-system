#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import shutil
import sys
import traceback
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


TARGET_MODULES = [
    "code_executor",
    "code_inserter",
    "code_reader",
    "code_reviewer",
    "system_control",
    "system_monitor",
]

WRAPPER_START = "# === SANHUA_OFFICIAL_WRAPPER_START ==="
WRAPPER_END = "# === SANHUA_OFFICIAL_WRAPPER_END ==="


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PatchResult:
    module: str
    ok: bool
    applied: bool
    reason: str
    module_py_changed: bool = False
    manifest_changed: bool = False
    wrapper_class_name: str = ""
    module_backup: str = ""
    manifest_backup: str = ""
    module_diff_preview: str = ""
    manifest_diff_preview: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
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
            pass
    return path.read_text(errors="ignore")


def safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_json_load(path: Path) -> Tuple[Dict, Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        obj = json.loads(safe_read_text(path))
        if isinstance(obj, dict):
            return obj, None
        return {}, "manifest_not_dict"
    except Exception as e:
        return {}, str(e)


def json_dumps_pretty(obj: Dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def rel_module_import(py_file: Path, root: Path) -> str:
    rel = py_file.resolve().relative_to(root.resolve())
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def unified_diff(old: str, new: str, path: str, after_label: str = "(after)") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} {after_label}",
            lineterm="",
        )
    )


def backup_file(src: Path, backup_root: Path, root: Path) -> str:
    rel = src.resolve().relative_to(root.resolve())
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def camelize(name: str) -> str:
    parts = [p for p in name.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) if parts else "Unknown"


# ============================================================
# AST 工具
# ============================================================

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
    out: List[str] = []
    for cls_name, bases in parse_classes(py_text, filename=filename):
        for base in bases:
            if base == "BaseModule" or base.endswith(".BaseModule") or base.endswith("BaseModule"):
                out.append(cls_name)
                break
    return out


# ============================================================
# BaseModule import 路径探测
# ============================================================

def choose_base_module_import(root: Path) -> str:
    preferred = [
        "core.core2_0.sanhuatongyu.module.base",
        "core.core2_0.sanhuatongyu.module.base_module",
    ]

    for candidate in preferred:
        py_path = root / Path(candidate.replace(".", "/") + ".py")
        if py_path.exists():
            return candidate

    # fallback 扫描
    candidates: List[str] = []
    for py in root.rglob("*.py"):
        try:
            text = safe_read_text(py)
            if "class BaseModule" in text:
                candidates.append(rel_module_import(py, root))
        except Exception:
            pass

    if not candidates:
        raise RuntimeError("未找到 BaseModule 定义")

    candidates = sorted(set(candidates), key=lambda x: (0 if x.endswith(".base") else 1, len(x), x))
    return candidates[0]


# ============================================================
# Wrapper 生成
# ============================================================

def build_wrapper_block(module_name: str, wrapper_class_name: str, base_module_import: str) -> str:
    return f'''
{WRAPPER_START}
try:
    from {base_module_import} import BaseModule as _SanhuaBaseModule
except Exception:
    _SanhuaBaseModule = object


def _sanhua_safe_call(_fn, *args, **kwargs):
    if not callable(_fn):
        return None

    last_error = None

    trials = [
        lambda: _fn(*args, **kwargs),
        lambda: _fn(*args),
        lambda: _fn(),
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


class {wrapper_class_name}(_SanhuaBaseModule):
    """
    Auto-generated official wrapper for legacy module: {module_name}
    """

    def __init__(self, *args, **kwargs):
        context = kwargs.pop("context", None) if "context" in kwargs else None
        self.context = context
        self.dispatcher = kwargs.get("dispatcher")
        self.started = False

        try:
            super().__init__(*args, **kwargs)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass

        if self.context is None:
            self.context = context

    def _resolve_dispatcher(self, context=None):
        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            obj = getattr(self, name, None)
            if obj is not None:
                return obj

        if isinstance(context, dict):
            for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
                obj = context.get(name)
                if obj is not None:
                    return obj

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        return None

    def setup(self, context=None):
        if context is not None:
            self.context = context

        self.dispatcher = self._resolve_dispatcher(context or self.context)

        _register = globals().get("register_actions")
        if callable(_register) and self.dispatcher is not None:
            _sanhua_safe_call(_register, self.dispatcher)

        _legacy_setup = globals().get("setup")
        if callable(_legacy_setup):
            try:
                _sanhua_safe_call(_legacy_setup, context or self.context)
            except Exception:
                pass

        return {{
            "ok": True,
            "module": "{module_name}",
            "view": "setup",
            "dispatcher_ready": self.dispatcher is not None,
            "legacy_wrapped": True,
        }}

    def start(self):
        _legacy_start = globals().get("start")
        if callable(_legacy_start):
            try:
                _sanhua_safe_call(_legacy_start)
            except Exception:
                pass

        self.started = True
        return {{
            "ok": True,
            "module": "{module_name}",
            "view": "start",
            "started": True,
        }}

    def stop(self):
        _legacy_stop = globals().get("stop") or globals().get("shutdown")
        if callable(_legacy_stop):
            try:
                _sanhua_safe_call(_legacy_stop)
            except Exception:
                pass

        self.started = False
        return {{
            "ok": True,
            "module": "{module_name}",
            "view": "stop",
            "started": False,
        }}

    def health_check(self):
        _legacy_health = globals().get("health_check")
        if callable(_legacy_health):
            try:
                result = _sanhua_safe_call(_legacy_health)
                if isinstance(result, dict):
                    result.setdefault("ok", True)
                    result.setdefault("module", "{module_name}")
                    result.setdefault("view", "health_check")
                    return result
                return {{
                    "ok": True,
                    "module": "{module_name}",
                    "view": "health_check",
                    "data": result,
                }}
            except Exception as e:
                return {{
                    "ok": False,
                    "module": "{module_name}",
                    "view": "health_check",
                    "reason": str(e),
                }}

        return {{
            "ok": True,
            "module": "{module_name}",
            "view": "health_check",
            "started": self.started,
            "legacy_wrapped": True,
        }}


def official_entry(context=None):
    _instance = {wrapper_class_name}(context=context)
    _instance.setup(context=context)
    return _instance
{WRAPPER_END}
'''.lstrip("\n")


def upsert_wrapper(module_text: str, wrapper_block: str) -> str:
    if WRAPPER_START in module_text and WRAPPER_END in module_text:
        start = module_text.index(WRAPPER_START)
        end = module_text.index(WRAPPER_END) + len(WRAPPER_END)
        return module_text[:start].rstrip() + "\n\n" + wrapper_block.rstrip() + "\n"
    return module_text.rstrip() + "\n\n" + wrapper_block.rstrip() + "\n"


# ============================================================
# manifest 处理
# ============================================================

def build_manifest(current: Dict, module_name: str, wrapper_class_name: str) -> Dict:
    data = dict(current or {})
    data["name"] = module_name
    data["entry"] = "module.py"
    data["entry_class"] = f"modules.{module_name}.module.{wrapper_class_name}"

    if "enabled" not in data:
        data["enabled"] = True
    if not data.get("status"):
        data["status"] = "active" if data.get("enabled", True) else "disabled"
    if "market_compatible" not in data:
        data["market_compatible"] = True

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

    ordered: Dict = {}
    for key in preferred_order:
        if key in data:
            ordered[key] = data[key]
    for key, value in data.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


# ============================================================
# 校验
# ============================================================

def validate_module_py(module_py: Path, root: Path, wrapper_class_name: str) -> Tuple[bool, str]:
    try:
        compile(safe_read_text(module_py), str(module_py), "exec")
    except Exception as e:
        return False, f"py_compile_failed: {e}"

    import_name = rel_module_import(module_py, root)
    try:
        mod = __import__(import_name, fromlist=[wrapper_class_name])
        cls = getattr(mod, wrapper_class_name, None)
        if cls is None:
            return False, f"class_not_found: {wrapper_class_name}"
        return True, "ok"
    except Exception as e:
        return False, f"import_failed: {e}"


def validate_manifest(manifest_path: Path, wrapper_class_name: str) -> Tuple[bool, str]:
    obj, err = safe_json_load(manifest_path)
    if err:
        return False, f"json_invalid: {err}"

    entry_class = obj.get("entry_class")
    if not isinstance(entry_class, str):
        return False, "entry_class_missing"
    if not entry_class.endswith("." + wrapper_class_name):
        return False, f"entry_class_mismatch: {entry_class}"
    return True, "ok"


# ============================================================
# 单模块处理
# ============================================================

def patch_single_module(root: Path, module_name: str, base_module_import: str, apply: bool, backup_root: Path) -> PatchResult:
    module_dir = root / "modules" / module_name
    module_py = module_dir / "module.py"
    manifest_json = module_dir / "manifest.json"

    if not module_py.exists():
        return PatchResult(module=module_name, ok=False, applied=apply, reason=f"module.py 不存在: {module_py}")

    old_module_text = safe_read_text(module_py)
    old_manifest_obj, manifest_err = safe_json_load(manifest_json)
    if manifest_err:
        return PatchResult(module=module_name, ok=False, applied=apply, reason=f"manifest 读取失败: {manifest_err}")

    classes = parse_classes(old_module_text, filename=str(module_py))
    class_names = [x[0] for x in classes]
    base_subclasses = find_base_subclasses(old_module_text, filename=str(module_py))

    wrapper_class_name = f"Official{camelize(module_name)}Module"
    idx = 2
    while wrapper_class_name in class_names:
        wrapper_class_name = f"Official{camelize(module_name)}Module{idx}"
        idx += 1

    notes: List[str] = []
    notes.append(f"existing_base_subclasses={base_subclasses}")

    need_module_patch = len(base_subclasses) == 0
    if need_module_patch:
        wrapper_block = build_wrapper_block(module_name, wrapper_class_name, base_module_import)
        new_module_text = upsert_wrapper(old_module_text, wrapper_block)
        notes.append("未发现 BaseModule 子类，注入 official wrapper")
    else:
        new_module_text = old_module_text
        wrapper_class_name = base_subclasses[0]
        notes.append(f"已存在 BaseModule 子类，复用 {wrapper_class_name}")

    new_manifest_obj = build_manifest(old_manifest_obj, module_name, wrapper_class_name)
    need_manifest_patch = new_manifest_obj != old_manifest_obj

    result = PatchResult(
        module=module_name,
        ok=True,
        applied=apply,
        reason="preview_ok" if not apply else "apply_ok",
        module_py_changed=need_module_patch,
        manifest_changed=need_manifest_patch,
        wrapper_class_name=wrapper_class_name,
        notes=notes,
    )

    if need_module_patch:
        result.module_diff_preview = unified_diff(old_module_text, new_module_text, str(module_py), "(after-patch)")
    if need_manifest_patch:
        result.manifest_diff_preview = unified_diff(
            json_dumps_pretty(old_manifest_obj),
            json_dumps_pretty(new_manifest_obj),
            str(manifest_json),
            "(after-patch)",
        )

    if not apply:
        return result

    module_backup = ""
    manifest_backup = ""

    try:
        if need_module_patch:
            module_backup = backup_file(module_py, backup_root, root)
            safe_write_text(module_py, new_module_text)
            ok, reason = validate_module_py(module_py, root, wrapper_class_name)
            if not ok:
                raise RuntimeError(reason)

        if need_manifest_patch:
            if manifest_json.exists():
                manifest_backup = backup_file(manifest_json, backup_root, root)
            else:
                manifest_json.parent.mkdir(parents=True, exist_ok=True)

            safe_write_text(manifest_json, json_dumps_pretty(new_manifest_obj))
            ok, reason = validate_manifest(manifest_json, wrapper_class_name)
            if not ok:
                raise RuntimeError(reason)

        result.module_backup = module_backup
        result.manifest_backup = manifest_backup
        result.ok = True
        result.reason = "apply_ok"
        return result

    except Exception as e:
        # rollback
        try:
            if module_backup:
                shutil.copy2(module_backup, module_py)
            if manifest_backup:
                shutil.copy2(manifest_backup, manifest_json)
        except Exception as rollback_e:
            result.notes.append(f"rollback_failed={rollback_e}")

        result.ok = False
        result.reason = f"apply_failed: {e}"
        return result


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="将 legacy action 模块 official 化为 BaseModule wrapper")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="指定模块，可重复")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    parser.add_argument("--report-json", default="", help="报告输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    ensure_sys_path(root)

    selected_modules = args.module or list(TARGET_MODULES)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / timestamp
    report_json = Path(args.report_json).resolve() if args.report_json else (root / "audit_output" / "patch_legacy_modules_to_official_v1_report.json")
    report_json.parent.mkdir(parents=True, exist_ok=True)

    try:
        base_module_import = choose_base_module_import(root)
    except Exception as e:
        log(f"[ERROR] BaseModule import 路径探测失败: {e}")
        return 3

    log("=" * 100)
    log("patch_legacy_modules_to_official_v1 开始")
    log("=" * 100)
    log(f"root               : {root}")
    log(f"apply              : {args.apply}")
    log(f"base_module_import : {base_module_import}")
    log(f"modules            : {selected_modules}")

    results: List[PatchResult] = []

    for module_name in selected_modules:
        log("-" * 100)
        log(f"[PATCH] {module_name}")
        try:
            res = patch_single_module(root, module_name, base_module_import, args.apply, backup_root)
            results.append(res)

            log(f"  ok                 : {res.ok}")
            log(f"  reason             : {res.reason}")
            log(f"  wrapper_class_name : {res.wrapper_class_name}")
            log(f"  module_py_changed  : {res.module_py_changed}")
            log(f"  manifest_changed   : {res.manifest_changed}")
            for note in res.notes:
                log(f"  note               : {note}")
            if res.module_backup:
                log(f"  module_backup      : {res.module_backup}")
            if res.manifest_backup:
                log(f"  manifest_backup    : {res.manifest_backup}")

            if res.module_diff_preview:
                log("  [module.py diff preview]")
                preview = res.module_diff_preview[:2200]
                log(preview + ("..." if len(res.module_diff_preview) > 2200 else ""))

            if res.manifest_diff_preview:
                log("  [manifest diff preview]")
                preview = res.manifest_diff_preview[:2200]
                log(preview + ("..." if len(res.manifest_diff_preview) > 2200 else ""))

        except Exception as e:
            tb = traceback.format_exc()
            log(f"  ok                 : False")
            log(f"  reason             : {e}")
            log(tb)
            results.append(PatchResult(module=module_name, ok=False, applied=args.apply, reason=str(e), notes=[tb]))

    total_ok = sum(1 for x in results if x.ok)
    total_fail = sum(1 for x in results if not x.ok)

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "apply": bool(args.apply),
        "base_module_import": base_module_import,
        "selected_modules": selected_modules,
        "results": [x.to_dict() for x in results],
        "summary": {
            "total_modules": len(selected_modules),
            "total_ok": total_ok,
            "total_fail": total_fail,
            "backup_root": str(backup_root) if args.apply else "",
        },
    }
    report_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log()
    log("=" * 100)
    log("patch_legacy_modules_to_official_v1 完成")
    log("=" * 100)
    log(f"total_ok    : {total_ok}")
    log(f"total_fail  : {total_fail}")
    log(f"report_json : {report_json}")
    if args.apply:
        log(f"backup_root : {backup_root}")
    log("=" * 100)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
