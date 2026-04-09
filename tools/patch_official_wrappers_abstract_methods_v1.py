#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import traceback
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


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


@dataclass
class PatchResult:
    module: str
    ok: bool
    applied: bool
    reason: str
    changed: bool = False
    backup_path: str = ""
    wrapper_class_name: str = ""
    added_methods: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def log(*args, **kwargs) -> None:
    print(*args, **kwargs)


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


def backup_file(src: Path, backup_root: Path, root: Path) -> str:
    rel = src.resolve().relative_to(root.resolve())
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def rel_module_import(py_file: Path, root: Path) -> str:
    rel = py_file.resolve().relative_to(root.resolve())
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def validate_module(module_py: Path, root: Path, wrapper_class_name: str) -> str:
    text = safe_read_text(module_py)
    compile(text, str(module_py), "exec")

    import_name = rel_module_import(module_py, root)
    mod = __import__(import_name, fromlist=[wrapper_class_name])
    cls = getattr(mod, wrapper_class_name, None)
    if cls is None:
        raise RuntimeError(f"class_not_found: {wrapper_class_name}")

    abstract_methods = sorted(getattr(cls, "__abstractmethods__", set()) or set())
    if abstract_methods:
        raise RuntimeError(f"abstract_methods_remaining: {abstract_methods}")

    return "ok"


def extract_wrapper_class_name(wrapper_block: str) -> str:
    m = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", wrapper_block)
    return m.group(1) if m else ""


def build_missing_methods_snippet(wrapper_class_name: str, module_name: str, need_preload: bool, need_handle_event: bool) -> str:
    chunks: List[str] = []

    if need_preload:
        chunks.append(
            '''
    def preload(self):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 无需复杂预加载时，默认返回成功。
        """
        return {
            "ok": True,
            "module": "%s",
            "view": "preload",
            "started": self.started,
            "wrapper": "%s",
            "legacy_wrapped": True,
        }
''' % (module_name, wrapper_class_name)
        )

    if need_handle_event:
        chunks.append(
            '''
    def handle_event(self, event_name, payload=None):
        """
        补齐 BaseModule 抽象契约：
        legacy action module 默认不消费事件，返回 noop/ignored。
        """
        return {
            "ok": True,
            "module": "%s",
            "view": "handle_event",
            "event_name": event_name,
            "payload": payload,
            "handled": False,
            "reason": "noop_legacy_wrapper",
            "wrapper": "%s",
        }
''' % (module_name, wrapper_class_name)
        )

    return "\n".join(x.strip("\n") for x in chunks).rstrip() + "\n"


def patch_wrapper_block(module_name: str, wrapper_block: str) -> (str, List[str], str):
    wrapper_class_name = extract_wrapper_class_name(wrapper_block)
    if not wrapper_class_name:
        raise RuntimeError("wrapper_class_name_not_found")

    has_preload = re.search(r"^\s+def\s+preload\s*\(", wrapper_block, flags=re.M) is not None
    has_handle_event = re.search(r"^\s+def\s+handle_event\s*\(", wrapper_block, flags=re.M) is not None

    added_methods: List[str] = []
    need_preload = not has_preload
    need_handle_event = not has_handle_event

    if not need_preload and not need_handle_event:
        return wrapper_block, added_methods, wrapper_class_name

    if need_preload:
        added_methods.append("preload")
    if need_handle_event:
        added_methods.append("handle_event")

    insert_anchor = "\ndef official_entry("
    idx = wrapper_block.find(insert_anchor)
    if idx == -1:
        raise RuntimeError("official_entry_anchor_not_found")

    snippet = build_missing_methods_snippet(
        wrapper_class_name=wrapper_class_name,
        module_name=module_name,
        need_preload=need_preload,
        need_handle_event=need_handle_event,
    )

    new_block = wrapper_block[:idx].rstrip() + "\n\n" + snippet + "\n" + wrapper_block[idx:].lstrip("\n")
    return new_block, added_methods, wrapper_class_name


def patch_single_module(root: Path, module_name: str, apply: bool, backup_root: Path) -> PatchResult:
    module_py = root / "modules" / module_name / "module.py"
    if not module_py.exists():
        return PatchResult(
            module=module_name,
            ok=False,
            applied=apply,
            reason=f"module.py_not_found: {module_py}",
        )

    text = safe_read_text(module_py)
    if WRAPPER_START not in text or WRAPPER_END not in text:
        return PatchResult(
            module=module_name,
            ok=False,
            applied=apply,
            reason="official_wrapper_block_not_found",
        )

    start = text.index(WRAPPER_START)
    end = text.index(WRAPPER_END) + len(WRAPPER_END)
    wrapper_block = text[start:end]

    new_wrapper_block, added_methods, wrapper_class_name = patch_wrapper_block(module_name, wrapper_block)

    if not added_methods:
        return PatchResult(
            module=module_name,
            ok=True,
            applied=apply,
            reason="already_complete",
            changed=False,
            wrapper_class_name=wrapper_class_name,
        )

    new_text = text[:start] + new_wrapper_block + text[end:]

    if not apply:
        return PatchResult(
            module=module_name,
            ok=True,
            applied=False,
            reason="preview_ok",
            changed=True,
            wrapper_class_name=wrapper_class_name,
            added_methods=added_methods,
        )

    backup_path = ""
    try:
        backup_path = backup_file(module_py, backup_root, root)
        safe_write_text(module_py, new_text)
        validate_module(module_py, root, wrapper_class_name)

        return PatchResult(
            module=module_name,
            ok=True,
            applied=True,
            reason="apply_ok",
            changed=True,
            backup_path=backup_path,
            wrapper_class_name=wrapper_class_name,
            added_methods=added_methods,
        )
    except Exception as e:
        try:
            if backup_path:
                shutil.copy2(backup_path, module_py)
        except Exception:
            pass

        return PatchResult(
            module=module_name,
            ok=False,
            applied=True,
            reason=f"apply_failed: {e}",
            changed=False,
            backup_path=backup_path,
            wrapper_class_name=wrapper_class_name,
            added_methods=added_methods,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐 official wrapper 的 BaseModule 抽象方法")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--module", action="append", default=[], help="指定模块，可重复")
    parser.add_argument("--apply", action="store_true", help="正式写入")
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
    report_json = Path(args.report_json).resolve() if args.report_json else (
        root / "audit_output" / "patch_official_wrappers_abstract_methods_v1_report.json"
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    log("=" * 100)
    log("patch_official_wrappers_abstract_methods_v1 开始")
    log("=" * 100)
    log(f"root    : {root}")
    log(f"apply   : {args.apply}")
    log(f"modules : {selected_modules}")

    results: List[PatchResult] = []

    for module_name in selected_modules:
        log("-" * 100)
        log(f"[PATCH] {module_name}")
        try:
            res = patch_single_module(root, module_name, args.apply, backup_root)
            results.append(res)
            log(f"  ok                 : {res.ok}")
            log(f"  reason             : {res.reason}")
            log(f"  changed            : {res.changed}")
            log(f"  wrapper_class_name : {res.wrapper_class_name}")
            log(f"  added_methods      : {res.added_methods}")
            if res.backup_path:
                log(f"  backup_path        : {res.backup_path}")
        except Exception as e:
            tb = traceback.format_exc()
            log(f"  ok                 : False")
            log(f"  reason             : {e}")
            log(tb)
            results.append(PatchResult(
                module=module_name,
                ok=False,
                applied=args.apply,
                reason=str(e),
            ))

    total_ok = sum(1 for x in results if x.ok)
    total_fail = sum(1 for x in results if not x.ok)

    output = {
        "ok": total_fail == 0,
        "root": str(root),
        "apply": bool(args.apply),
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
    log("patch_official_wrappers_abstract_methods_v1 完成")
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
