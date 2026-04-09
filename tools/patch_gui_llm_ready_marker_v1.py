#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
from pathlib import Path


PATCH_MARKER = "SANHUA_GUI_LLM_READY_MARKER_V1"
TARGET_REL = "entry/gui_entry/gui_main.py"


INJECT_BLOCK = r'''
# === SANHUA_GUI_LLM_READY_MARKER_V1 START ===
try:
    import os as _sanhua_gui_os

    _backend = (
        _sanhua_gui_os.getenv("SANHUA_LLM_BACKEND")
        or _sanhua_gui_os.getenv("AICORE_LLM_BACKEND")
        or "unknown"
    ).strip()

    _model = (
        _sanhua_gui_os.getenv("SANHUA_ACTIVE_MODEL")
        or _sanhua_gui_os.getenv("SANHUA_MODEL")
        or _sanhua_gui_os.getenv("SANHUA_MODEL_NAME")
        or _sanhua_gui_os.getenv("SANHUA_LLAMA_MODEL")
        or ""
    ).strip()

    _base_url = (
        _sanhua_gui_os.getenv("SANHUA_LLAMA_BASE_URL")
        or _sanhua_gui_os.getenv("SANHUA_SERVER")
        or _sanhua_gui_os.getenv("OPENAI_BASE_URL")
        or ""
    ).strip()

    if _model and _base_url:
        print(f"🧠 LLM 就绪：{_backend} / {_model} / {_base_url}")
    elif _model:
        print(f"🧠 LLM 就绪：{_backend} / {_model}")
    elif _base_url:
        print(f"🧠 LLM 就绪：{_backend} / {_base_url}")
    else:
        print(f"🧠 LLM 就绪：{_backend}")
except Exception as _e:
    print(f"⚠️ LLM readiness marker emit failed: {_e}")
# === SANHUA_GUI_LLM_READY_MARKER_V1 END ===
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


def patch_text(text: str) -> tuple[str, str | None]:
    if PATCH_MARKER in text:
        return text, "already_patched"

    lines = text.splitlines(keepends=True)

    anchor_indexes = []
    for i, line in enumerate(lines):
        if "✅ actions registered into ACTION_MANAGER" in line:
            anchor_indexes.append(i)

    if not anchor_indexes:
        for i, line in enumerate(lines):
            if "aliases loaded =" in line:
                anchor_indexes.append(i - 1 if i > 0 else 0)
                break

    if not anchor_indexes:
        return text, "anchor_not_found"

    idx = anchor_indexes[0]
    insert_at = idx + 1

    block = INJECT_BLOCK + "\n"
    patched = "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])
    return patched, None


def main() -> int:
    parser = argparse.ArgumentParser(description="为 GUI 注入标准化 LLM ready 启动标记")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / TARGET_REL

    log("=" * 100)
    log("patch_gui_llm_ready_marker_v1")
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
