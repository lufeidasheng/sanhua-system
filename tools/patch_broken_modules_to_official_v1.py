#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import difflib
import importlib
import json
import os
import shutil
import sys
import textwrap
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PatchResult:
    module: str
    ok: bool
    reason: str
    wrapper_class_name: str = ""
    module_py_changed: bool = False
    manifest_changed: bool = False
    module_backup: str = ""
    manifest_backup: str = ""
    notes: List[str] = field(default_factory=list)
    module_diff_preview: str = ""
    manifest_diff_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 基础工具
# ============================================================

DEFAULT_TARGET_MODULES = [
    "model_engine_actions",
    "state_describe",
]

WRAPPER_START = "# === SANHUA_OFFICIAL_WRAPPER_START ==="
WRAPPER_END = "# === SANHUA_OFFICIAL_WRAPPER_END ==="


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


def safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def write_json_text(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def relpath_posix(path: Path, root: Path) -> str:
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def make_unified_diff(old_text: str, new_text: str, path: str, after_label: str = "(after-patch)") -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{path} (before)",
        tofile=f"{path} {after_label}",
        lineterm="",
    )
    return "".join(diff)


def backup_file(path: Path, backup_root: Path) -> str:
    target = backup_root / path.relative_to(path.anchor if path.is_absolute() else Path("."))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return str(target)


def class_name_from_module(module_name: str) -> str:
    parts = [p for p in module_name.replace("-", "_").split("_") if p]
    base = "".join(p[:1].upper() + p[1:] for p in parts)
    return f"Official{base}Module"


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


def parse_ast_classes(module_text: str, filename: str) -> List[Tuple[str, List[str]]]:
    try:
        tree = ast.parse(module_text, filename=filename)
    except Exception:
        return []

    classes: List[Tuple[str, List[str]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [extract_base_name(b) for b in node.bases]
            classes.append((node.name, bases))
    return classes


def discover_base_subclasses(module_text: str, filename: str) -> List[str]:
    out: List[str] = []
    for name, bases in parse_ast_classes(module_text, filename):
        if any(base.endswith("BaseModule") or base == "BaseModule" for base in bases):
            out.append(name)
    return out


def discover_candidate_legacy_classes(
    module_text: str,
    filename: str,
    wrapper_class_name: str,
    manifest_entry_class_name: str = "",
) -> List[str]:
    classes = parse_ast_classes(module_text, filename)
    names = [name for name, _ in classes]

    ordered: List[str] = []

    def push(x: str) -> None:
        if x and x not in ordered and x != wrapper_class_name:
            ordered.append(x)

    push(manifest_entry_class_name)

    for name in names:
        if name.endswith("Module"):
            push(name)
    for name in names:
        push(name)

    return ordered


def ensure_wrapper_methods_exist(wrapper_code: str) -> str:
    return wrapper_code


def replace_or_append_wrapper(module_text: str, wrapper_code: str) -> str:
    if WRAPPER_START in module_text and WRAPPER_END in module_text:
        start = module_text.index(WRAPPER_START)
        end = module_text.index(WRAPPER_END) + len(WRAPPER_END)
        prefix = module_text[:start].rstrip()
        suffix = module_text[end:].lstrip()
        merged = prefix + "\n\n" + wrapper_code.strip() + "\n"
        if suffix:
            merged += "\n" + suffix
        return merged

    merged = module_text.rstrip() + "\n\n" + wrapper_code.strip() + "\n"
    return merged


def update_manifest_entry_class(
    manifest_obj: Dict[str, Any],
    wrapper_entry_class: str,
) -> Tuple[Dict[str, Any], bool]:
    data = dict(manifest_obj or {})
    changed = False

    if data.get("entry") != "module.py":
        data["entry"] = "module.py"
        changed = True

    if data.get("entry_class") != wrapper_entry_class:
        data["entry_class"] = wrapper_entry_class
        changed = True

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

    return ordered, changed


# ============================================================
# Wrapper 代码生成
# ============================================================

def build_wrapper_code(
    module_name: str,
    wrapper_class_name: str,
    legacy_candidates: List[str],
) -> str:
    candidate_list = json.dumps(legacy_candidates, ensure_ascii=False)

    code = f"""
{WRAPPER_START}
try:
    from core.core2_0.sanhuatongyu.module.base import BaseModule as _SanhuaBaseModule
except Exception:
    _SanhuaBaseModule = object


def _sanhua_safe_call(_fn, *args, **kwargs):
    if not callable(_fn):
        return None

    _last_error = None
    _trials = [
        lambda: _fn(*args, **kwargs),
        lambda: _fn(*args),
        lambda: _fn(),
    ]

    for _call in _trials:
        try:
            return _call()
        except TypeError as _e:
            _last_error = _e
            continue

    if _last_error is not None:
        raise _last_error
    return None


def _sanhua_find_legacy_target():
    _candidates = {candidate_list}
    for _name in _candidates:
        _obj = globals().get(_name)
        if isinstance(_obj, type) and _name != "{wrapper_class_name}":
            return _obj
    return None


class {wrapper_class_name}(_SanhuaBaseModule):
    \"\"\"
    Auto-generated official wrapper for broken module: {module_name}
    \"\"\"

    def __init__(self, *args, **kwargs):
        _context = kwargs.pop("context", None) if "context" in kwargs else None
        self.context = _context
        self.dispatcher = kwargs.get("dispatcher")
        self.started = False
        self._legacy_cls = _sanhua_find_legacy_target()
        self._legacy = None

        try:
            super().__init__(*args, **kwargs)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass

        if self.context is None:
            self.context = _context

    def _resolve_dispatcher(self, context=None):
        for _name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            _obj = getattr(self, _name, None)
            if _obj is not None:
                return _obj

        if isinstance(context, dict):
            for _name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
                _obj = context.get(_name)
                if _obj is not None:
                    return _obj

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        return None

    def _ensure_legacy(self):
        if self._legacy is not None:
            return self._legacy
        if self._legacy_cls is None:
            return None

        _dispatcher = self._resolve_dispatcher(self.context)

        _builders = [
            lambda: self._legacy_cls(context=self.context, dispatcher=_dispatcher),
            lambda: self._legacy_cls(dispatcher=_dispatcher),
            lambda: self._legacy_cls(context=self.context),
            lambda: self._legacy_cls(),
        ]

        _last_error = None
        for _builder in _builders:
            try:
                self._legacy = _builder()
                break
            except TypeError as _e:
                _last_error = _e
                continue
            except Exception:
                raise

        if self._legacy is None and _last_error is not None:
            raise _last_error

        return self._legacy

    def preload(self):
        _legacy = self._ensure_legacy()
        if _legacy is None:
            return {{"ok": True, "source": "{module_name}", "view": "preload", "wrapped": False}}

        _fn = getattr(_legacy, "preload", None)
        if callable(_fn):
            _ret = _sanhua_safe_call(_fn)
            return _ret if _ret is not None else {{"ok": True, "source": "{module_name}", "view": "preload", "wrapped": True}}

        return {{"ok": True, "source": "{module_name}", "view": "preload", "wrapped": True}}

    def setup(self):
        _dispatcher = self._resolve_dispatcher(self.context)
        if _dispatcher is not None and getattr(self, "dispatcher", None) is None:
            self.dispatcher = _dispatcher

        _legacy = self._ensure_legacy()

        if _legacy is not None:
            for _name in ("preload", "setup"):
                _fn = getattr(_legacy, _name, None)
                if callable(_fn):
                    _sanhua_safe_call(_fn)

            _reg = getattr(_legacy, "register_actions", None)
            if callable(_reg):
                _sanhua_safe_call(_reg, self.dispatcher)

        _module_reg = globals().get("register_actions")
        if callable(_module_reg):
            try:
                _sanhua_safe_call(_module_reg, self.dispatcher)
            except Exception:
                # 模块级 register_actions 失败时不让 wrapper setup 整体崩掉
                pass

        return {{"ok": True, "source": "{module_name}", "view": "setup"}}

    def start(self):
        _legacy = self._ensure_legacy()
        _fn = getattr(_legacy, "start", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = True
        return {{"ok": True, "source": "{module_name}", "view": "start"}}

    def stop(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "stop", None) if _legacy is not None else None
        if callable(_fn):
            _sanhua_safe_call(_fn)
        self.started = False
        return {{"ok": True, "source": "{module_name}", "view": "stop"}}

    def health_check(self):
        _legacy = self._legacy
        _fn = getattr(_legacy, "health_check", None) if _legacy is not None else None
        if callable(_fn):
            try:
                _ret = _sanhua_safe_call(_fn)
                if isinstance(_ret, dict):
                    _ret.setdefault("ok", True)
                    _ret.setdefault("source", "{module_name}")
                    _ret.setdefault("view", "health_check")
                    return _ret
            except Exception as _e:
                return {{
                    "ok": False,
                    "source": "{module_name}",
                    "view": "health_check",
                    "error": str(_e),
                }}

        return {{
            "ok": True,
            "source": "{module_name}",
            "view": "health_check",
            "started": bool(getattr(self, "started", False)),
            "wrapped": self._legacy is not None,
        }}

    def handle_event(self, event_name, payload=None):
        _legacy = self._ensure_legacy()
        _fn = getattr(_legacy, "handle_event", None) if _legacy is not None else None
        if callable(_fn):
            _ret = _sanhua_safe_call(_fn, event_name, payload)
            if _ret is not None:
                return _ret

        return {{
            "ok": True,
            "source": "{module_name}",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "ignored": True,
        }}


entry = {wrapper_class_name}
{WRAPPER_END}
"""
    return textwrap.dedent(code).strip() + "\n"


# ============================================================
# 单模块处理
# ============================================================

def patch_single_module(
    root: Path,
    module_name: str,
    *,
    apply: bool,
    backup_root: Path,
) -> PatchResult:
    module_dir = root / "modules" / module_name
    module_py = module_dir / "module.py"
    manifest_json = module_dir / "manifest.json"

    result = PatchResult(
        module=module_name,
        ok=False,
        reason="unknown",
    )

    if not module_py.exists():
        result.reason = f"module.py not found: {module_py}"
        return result

    wrapper_class_name = class_name_from_module(module_name)
    result.wrapper_class_name = wrapper_class_name

    module_text = safe_read_text(module_py)
    manifest_obj, manifest_error = safe_json_load(manifest_json)
    if manifest_error is not None and manifest_obj is None:
        result.reason = f"manifest invalid json: {manifest_error}"
        return result

    base_subclasses = discover_base_subclasses(module_text, str(module_py))
    result.notes.append(f"existing_base_subclasses={base_subclasses}")

    manifest_entry_class_name = ""
    if isinstance(manifest_obj, dict):
        entry_class = str(manifest_obj.get("entry_class") or "")
        if entry_class:
            manifest_entry_class_name = entry_class.split(".")[-1]

    legacy_candidates = discover_candidate_legacy_classes(
        module_text=module_text,
        filename=str(module_py),
        wrapper_class_name=wrapper_class_name,
        manifest_entry_class_name=manifest_entry_class_name,
    )

    if wrapper_class_name in base_subclasses:
        result.notes.append("已存在 official wrapper，将执行幂等替换")
    elif base_subclasses:
        result.notes.append("已存在其他 BaseModule 子类，但目标模块仍要求切换到指定 official wrapper")
    else:
        result.notes.append("未发现 BaseModule 子类，注入 official wrapper")

    wrapper_code = build_wrapper_code(
        module_name=module_name,
        wrapper_class_name=wrapper_class_name,
        legacy_candidates=legacy_candidates,
    )
    new_module_text = replace_or_append_wrapper(module_text, wrapper_code)
    result.module_py_changed = (new_module_text != module_text)
    result.module_diff_preview = make_unified_diff(module_text, new_module_text, str(module_py))

    wrapper_entry_class = f"modules.{module_name}.module.{wrapper_class_name}"
    manifest_current = manifest_obj or {}
    manifest_new_obj, manifest_changed = update_manifest_entry_class(manifest_current, wrapper_entry_class)
    new_manifest_text = write_json_text(manifest_new_obj)
    old_manifest_text = write_json_text(manifest_current) if manifest_current else safe_read_text(manifest_json)
    if not old_manifest_text and manifest_json.exists():
        old_manifest_text = safe_read_text(manifest_json)
    result.manifest_changed = manifest_changed or (new_manifest_text != old_manifest_text)
    result.manifest_diff_preview = make_unified_diff(old_manifest_text, new_manifest_text, str(manifest_json))

    if not apply:
        result.ok = True
        result.reason = "preview_ok"
        return result

    try:
        if result.module_py_changed:
            result.module_backup = backup_file(module_py, backup_root)
            safe_write_text(module_py, new_module_text)

        if result.manifest_changed:
            if manifest_json.exists():
                result.manifest_backup = backup_file(manifest_json, backup_root)
            safe_write_text(manifest_json, new_manifest_text)

        # 基础语法校验
        compile(new_module_text, str(module_py), "exec")
        json.loads(new_manifest_text)

        result.ok = True
        result.reason = "apply_ok"
        return result
    except Exception as e:
        result.ok = False
        result.reason = f"apply_failed: {e}"
        return result


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="将 broken module official 化为 BaseModule wrapper")
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

    selected = args.module or DEFAULT_TARGET_MODULES
    report_json = (
        Path(args.report_json).resolve()
        if args.report_json
        else root / "audit_output" / "patch_broken_modules_to_official_v1_report.json"
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    backup_root = root / "audit_output" / "fix_backups" / __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")

    log("=" * 100)
    log("patch_broken_modules_to_official_v1 开始")
    log("=" * 100)
    log(f"root               : {root}")
    log(f"apply              : {args.apply}")
    log(f"modules            : {selected}")

    results: List[PatchResult] = []
    total_ok = 0
    total_fail = 0

    for module_name in selected:
        log("-" * 100)
        log(f"[PATCH] {module_name}")
        try:
            res = patch_single_module(
                root=root,
                module_name=module_name,
                apply=args.apply,
                backup_root=backup_root,
            )
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
                preview = res.module_diff_preview
                if len(preview) > 2500:
                    preview = preview[:2500] + "...\n"
                log("  [module.py diff preview]")
                print(preview, end="" if preview.endswith("\n") else "\n")

            if res.manifest_diff_preview:
                preview = res.manifest_diff_preview
                if len(preview) > 1200:
                    preview = preview[:1200] + "...\n"
                log("  [manifest diff preview]")
                print(preview, end="" if preview.endswith("\n") else "\n")

            if res.ok:
                total_ok += 1
            else:
                total_fail += 1
        except Exception:
            total_fail += 1
            tb = traceback.format_exc()
            log(f"  ok                 : False")
            log(f"  reason             : crash")
            log(tb)
            results.append(
                PatchResult(
                    module=module_name,
                    ok=False,
                    reason="crash",
                    notes=[tb],
                )
            )

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "apply": bool(args.apply),
        "selected_modules": selected,
        "summary": {
            "total_ok": total_ok,
            "total_fail": total_fail,
        },
        "results": [r.to_dict() for r in results],
        "backup_root": str(backup_root) if args.apply else "",
    }
    report_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log()
    log("=" * 100)
    log("patch_broken_modules_to_official_v1 完成")
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
