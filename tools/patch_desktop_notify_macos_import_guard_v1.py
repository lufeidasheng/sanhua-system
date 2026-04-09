#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import os
import re
import shutil
from pathlib import Path


TARGET_REL = "modules/desktop_notify/module.py"
PATCH_MARKER = "SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1"


PATCH_BLOCK = r'''
# === SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1 START ===
import sys as _sanhua_dt_sys
import types as _sanhua_dt_types

if _sanhua_dt_sys.platform == "darwin":
    _fake_gi = _sanhua_dt_types.ModuleType("gi")

    def _sanhua_fake_require_version(*args, **kwargs):
        raise ImportError("gi disabled on darwin by SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1")

    _fake_gi.require_version = _sanhua_fake_require_version

    _fake_gi_repository = _sanhua_dt_types.ModuleType("gi.repository")
    _fake_gi.repository = _fake_gi_repository

    _sanhua_dt_sys.modules["gi"] = _fake_gi
    _sanhua_dt_sys.modules["gi.repository"] = _fake_gi_repository
# === SANHUA_DESKTOP_NOTIFY_DARWIN_IMPORT_GUARD_V1 END ===
'''.strip("\n")


def log(msg: str = "") -> None:
    print(msg)


def safe_read(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def backup_file(root: Path, target: Path) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / str(target).lstrip(os.sep)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def detect_encoding_line(lines: list[str], idx: int) -> int:
    if idx < len(lines):
        if re.search(r"coding[:=]\s*[-\w.]+", lines[idx]):
            return idx + 1
    return idx


def compute_insert_line(text: str) -> int:
    """
    返回应插入 patch block 的“行后位置”（1-based end line）。
    规则：
    1. 保留 shebang / coding
    2. 保留模块 docstring
    3. 保留 __future__ imports
    """
    lines = text.splitlines()
    base_idx = 0

    if lines and lines[0].startswith("#!"):
        base_idx = 1
    base_idx = detect_encoding_line(lines, base_idx)

    insert_after = base_idx  # 0-based count converted later

    try:
        tree = ast.parse(text)
    except Exception:
        return insert_after

    body = list(tree.body)
    pos = 0

    if body:
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            insert_after = max(insert_after, getattr(first, "end_lineno", first.lineno))
            pos = 1

    while pos < len(body):
        node = body[pos]
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_after = max(insert_after, getattr(node, "end_lineno", node.lineno))
            pos += 1
            continue
        break

    return insert_after


def patch_text(text: str) -> tuple[str, str | None]:
    if PATCH_MARKER in text:
        return text, "already_patched"

    lines = text.splitlines(keepends=True)
    insert_after = compute_insert_line(text)

    block = PATCH_BLOCK + "\n\n"

    if insert_after <= 0:
        patched = block + text
    else:
        idx = min(insert_after, len(lines))
        patched = "".join(lines[:idx]) + ("\n" if idx > 0 and not lines[idx - 1].endswith("\n") else "") + block + "".join(lines[idx:])

    return patched, None


def main() -> int:
    parser = argparse.ArgumentParser(description="为 desktop_notify 注入 macOS 顶层 gi import guard")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / TARGET_REL

    log("=" * 100)
    log("patch_desktop_notify_macos_import_guard_v1")
    log("=" * 100)
    log(f"root   : {root}")
    log(f"apply  : {args.apply}")
    log(f"target : {target}")

    if not target.exists():
        log(f"[ERROR] 文件不存在: {target}")
        return 2

    original = safe_read(target)
    patched, err = patch_text(original)

    if err == "already_patched":
        log("[SKIP] 已打过补丁")
        return 0

    if err is not None:
        log(f"[ERROR] patch 失败: {err}")
        return 3

    if not args.apply:
        log("[PREVIEW] 补丁可应用")
        return 0

    backup = backup_file(root, target)
    safe_write(target, patched)

    log(f"[BACKUP] {backup}")
    log(f"[PATCHED] {target}")
    log("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
