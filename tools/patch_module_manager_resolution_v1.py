#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys
from pathlib import Path


PATCH_MARKER = "SANHUA_MODULE_CLASS_RESOLUTION_PATCH_V1"


HELPER_BLOCK = r'''
    # === SANHUA_MODULE_CLASS_RESOLUTION_PATCH_V1 START ===
    def _sanhua_camelize_module_name(self, name):
        parts = [p for p in str(name).replace("-", "_").split("_") if p]
        return "".join(p[:1].upper() + p[1:] for p in parts)

    def _sanhua_pick_best_module_class(self, mod_meta, candidates):
        if not candidates:
            return None

        entry_class = getattr(mod_meta, "entry_class", "") or ""
        preferred_name = entry_class.rsplit(".", 1)[-1] if "." in entry_class else entry_class
        module_name = getattr(mod_meta, "name", "") or ""

        expected_names = []
        if preferred_name:
            expected_names.append(preferred_name)

        camel = self._sanhua_camelize_module_name(module_name) if module_name else ""
        if camel:
            expected_names.extend([
                f"Official{camel}Module",
                f"{camel}Module",
                camel,
            ])

        seen = set()
        ordered_names = []
        for name in expected_names:
            if name and name not in seen:
                seen.add(name)
                ordered_names.append(name)

        by_name = {cls.__name__: cls for cls in candidates}

        for name in ordered_names:
            cls = by_name.get(name)
            if cls is not None:
                return cls

        for cls in candidates:
            if cls.__name__.startswith("Official"):
                return cls

        for cls in candidates:
            try:
                if not inspect.isabstract(cls):
                    return cls
            except Exception:
                return cls

        return candidates[0]
    # === SANHUA_MODULE_CLASS_RESOLUTION_PATCH_V1 END ===

'''.lstrip("\n")


LOAD_MODULE_CLASS_BLOCK = r'''
    def _load_module_class(self, mod_meta):
        from core.core2_0.sanhuatongyu.module.base import BaseModule

        entry_class = getattr(mod_meta, "entry_class", "") or ""
        module_name = getattr(mod_meta, "name", "") or ""

        explicit_module_path = entry_class.rsplit(".", 1)[0] if "." in entry_class else ""
        explicit_class_name = entry_class.rsplit(".", 1)[-1] if "." in entry_class else entry_class

        candidate_module_paths = []
        for path in (
            explicit_module_path,
            f"modules.{module_name}.module" if module_name else "",
            f"modules.{module_name}" if module_name else "",
        ):
            if path and path not in candidate_module_paths:
                candidate_module_paths.append(path)

        module_obj = None
        import_errors = []

        for path in candidate_module_paths:
            try:
                module_obj = importlib.import_module(path)
                break
            except Exception as e:
                import_errors.append(f"{path}: {e}")

        if module_obj is None:
            raise ImportError(
                f"模块导入失败: {module_name} | tried={candidate_module_paths} | "
                f"errors={' | '.join(import_errors)}"
            )

        if explicit_class_name:
            explicit_cls = getattr(module_obj, explicit_class_name, None)
            if inspect.isclass(explicit_cls):
                try:
                    if issubclass(explicit_cls, BaseModule) and explicit_cls is not BaseModule:
                        return explicit_cls
                except Exception:
                    pass

        entry_obj = getattr(module_obj, "entry", None)
        if inspect.isclass(entry_obj):
            try:
                if issubclass(entry_obj, BaseModule) and entry_obj is not BaseModule:
                    return entry_obj
            except Exception:
                pass

        candidates = []
        for _, obj in vars(module_obj).items():
            if not inspect.isclass(obj):
                continue
            if obj is BaseModule:
                continue
            try:
                if not issubclass(obj, BaseModule):
                    continue
            except Exception:
                continue

            if getattr(obj, "__module__", None) != module_obj.__name__:
                continue

            candidates.append(obj)

        if not candidates:
            raise TypeError(f"未找到BaseModule子类: {module_name}")

        if len(candidates) == 1:
            return candidates[0]

        chosen = self._sanhua_pick_best_module_class(mod_meta, candidates)

        _logger = getattr(self, "logger", None)
        if _logger is not None:
            try:
                _logger.debug(
                    "multiple_basemodule_found: module=%s candidates=%s selected=%s",
                    module_name,
                    [cls.__name__ for cls in candidates],
                    getattr(chosen, "__name__", str(chosen)),
                )
            except Exception:
                pass

        return chosen
'''.lstrip("\n")


def log(msg: str = "") -> None:
    print(msg)


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text

    lines = text.splitlines(keepends=True)

    insert_at = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            insert_at = i + 1
            continue
        if s == "" and insert_at > 0:
            break
        if insert_at == 0 and s and not s.startswith("#") and not s.startswith('"""') and not s.startswith("'''"):
            break

    lines.insert(insert_at, import_line + "\n")
    return "".join(lines)


def find_def_block(text: str, def_name: str, indent: str = "    "):
    lines = text.splitlines(keepends=True)
    pattern = re.compile(rf"^{re.escape(indent)}def\s+{re.escape(def_name)}\s*\(")

    start = None
    for i, line in enumerate(lines):
        if pattern.match(line):
            start = i
            break

    if start is None:
        return None, None, None

    end = len(lines)
    next_def_pattern = re.compile(rf"^{re.escape(indent)}def\s+[A-Za-z_]\w*\s*\(")
    next_decorator_pattern = re.compile(rf"^{re.escape(indent)}@")

    for j in range(start + 1, len(lines)):
        line = lines[j]
        if next_def_pattern.match(line):
            end = j
            break
        if next_decorator_pattern.match(line):
            # 可能是下一个方法的 decorator
            k = j + 1
            while k < len(lines) and next_decorator_pattern.match(lines[k]):
                k += 1
            if k < len(lines) and next_def_pattern.match(lines[k]):
                end = j
                break

    return start, end, lines


def replace_def_block(text: str, def_name: str, new_block: str, indent: str = "    "):
    start, end, lines = find_def_block(text, def_name, indent=indent)
    if start is None:
        return None, f"def_not_found:{def_name}"

    if not new_block.endswith("\n"):
        new_block += "\n"

    new_lines = lines[:start] + [new_block] + lines[end:]
    return "".join(new_lines), None


def inject_helper_before(text: str, anchor_def: str, helper_block: str, indent: str = "    "):
    if PATCH_MARKER in text:
        return text, None

    start, _, lines = find_def_block(text, anchor_def, indent=indent)
    if start is None:
        return None, f"anchor_not_found:{anchor_def}"

    if not helper_block.endswith("\n"):
        helper_block += "\n"

    new_lines = lines[:start] + [helper_block] + lines[start:]
    return "".join(new_lines), None


def backup_file(root: Path, target: Path) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / str(target).lstrip(os.sep)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def patch_manager_text(original: str):
    text = original

    text = ensure_import(text, "import inspect")
    text = ensure_import(text, "import importlib")

    text2, err = inject_helper_before(text, "_load_module_class", HELPER_BLOCK, indent="    ")
    if err:
        return None, err
    text = text2

    text2, err = replace_def_block(text, "_load_module_class", LOAD_MODULE_CLASS_BLOCK, indent="    ")
    if err:
        return None, err
    text = text2

    return text, None


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 module manager 的 BaseModule 类解析与 multiple_basemodule_found 噪音")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "core2_0" / "sanhuatongyu" / "module" / "manager.py"

    log("=" * 100)
    log("patch_module_manager_resolution_v1")
    log("=" * 100)
    log(f"root   : {root}")
    log(f"apply  : {args.apply}")
    log(f"target : {target}")

    if not target.exists():
        log(f"[ERROR] 文件不存在: {target}")
        return 2

    original = read_text(target)
    patched, err = patch_manager_text(original)
    if err:
        log(f"[ERROR] patch 失败: {err}")
        return 3

    if patched == original:
        log("[SKIP] 未检测到需要变更的内容，或已是目标状态")
        return 0

    if not args.apply:
        log("[PREVIEW] 补丁可应用")
        return 0

    backup = backup_file(root, target)
    write_text(target, patched)

    log(f"[BACKUP] {backup}")
    log(f"[PATCHED] {target}")
    log("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
