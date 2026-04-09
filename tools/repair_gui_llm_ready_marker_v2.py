#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as _dt
import os
import py_compile
import shutil
from pathlib import Path


PATCH_NAME = "repair_gui_llm_ready_marker_v2"
TARGET_REL = "entry/gui_entry/gui_main.py"

MARKER_START = "# === SANHUA_GUI_LLM_READY_MARKER_V1 START ==="
MARKER_END = "# === SANHUA_GUI_LLM_READY_MARKER_V1 END ==="

RAW_BLOCK = r"""
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
""".strip("\n")


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


def make_backup(root: Path, target: Path) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / str(target).lstrip(os.sep)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def indent_block(block: str, indent: str) -> str:
    out = []
    for line in block.splitlines():
        if line.strip():
            out.append(indent + line)
        else:
            out.append("")
    return "\n".join(out)


def strip_old_marker(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if MARKER_START in line:
            start_idx = i
            break

    if start_idx is None:
        return text, False

    for i in range(start_idx, len(lines)):
        if MARKER_END in lines[i]:
            end_idx = i
            break

    if end_idx is None:
        # 保险处理：如果只有 START 没有 END，就从 START 删到下一个空行块结束前也不稳妥；
        # 这里直接删到文件尾，保证先把坏块去掉。
        cleaned = "\n".join(lines[:start_idx]).rstrip() + "\n"
        return cleaned, True

    cleaned_lines = lines[:start_idx] + lines[end_idx + 1 :]
    cleaned = "\n".join(cleaned_lines).rstrip() + "\n"
    return cleaned, True


def find_anchor(lines: list[str]) -> tuple[int | None, str | None]:
    preferred = [
        "✅ actions registered into ACTION_MANAGER",
        "🌸 aliases loaded =",
    ]
    for needle in preferred:
        for i, line in enumerate(lines):
            if needle in line:
                return i, needle
    return None, None


def patch_text(text: str) -> tuple[str, str | None, dict]:
    cleaned_text, removed_old = strip_old_marker(text)
    lines = cleaned_text.splitlines()

    anchor_idx, anchor_name = find_anchor(lines)
    if anchor_idx is None:
        return text, "anchor_not_found", {
            "removed_old": removed_old,
            "anchor_name": None,
            "anchor_idx": None,
            "indent_len": None,
        }

    anchor_line = lines[anchor_idx]
    indent = leading_ws(anchor_line)
    indented_block = indent_block(RAW_BLOCK, indent)

    insert_at = anchor_idx + 1
    patched_lines = lines[:insert_at] + [indented_block] + lines[insert_at:]
    patched = "\n".join(patched_lines).rstrip() + "\n"

    return patched, None, {
        "removed_old": removed_old,
        "anchor_name": anchor_name,
        "anchor_idx": anchor_idx + 1,
        "indent_len": len(indent.replace("\t", "    ")),
    }


def compile_file(path: Path) -> tuple[bool, str]:
    try:
        py_compile.compile(str(path), doraise=True)
        return True, "py_compile_ok"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 GUI LLM ready marker 缩进并重新注入")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / TARGET_REL

    log("=" * 100)
    log(PATCH_NAME)
    log("=" * 100)
    log(f"root   : {root}")
    log(f"apply  : {args.apply}")
    log(f"target : {target}")

    if not target.exists():
        log(f"[ERROR] 文件不存在: {target}")
        return 2

    original = safe_read(target)
    patched, err, meta = patch_text(original)

    if err is not None:
        log(f"[ERROR] patch 失败: {err}")
        return 3

    log(f"[INFO] removed_old_marker : {meta.get('removed_old')}")
    log(f"[INFO] anchor_name        : {meta.get('anchor_name')}")
    log(f"[INFO] anchor_line        : {meta.get('anchor_idx')}")
    log(f"[INFO] indent_len         : {meta.get('indent_len')}")

    if not args.apply:
        tmp_preview = target.with_suffix(target.suffix + ".tmp_preview")
        try:
            safe_write(tmp_preview, patched)
            ok, reason = compile_file(tmp_preview)
            if tmp_preview.exists():
                tmp_preview.unlink()
        except Exception:
            ok, reason = False, "preview_temp_compile_failed"

        if ok:
            log("[PREVIEW] 补丁可应用，且语法通过")
            return 0
        log(f"[ERROR] 预演后语法失败: {reason}")
        return 4

    backup = make_backup(root, target)
    safe_write(target, patched)

    ok, reason = compile_file(target)
    if not ok:
        shutil.copy2(backup, target)
        log(f"[ROLLBACK] 新文件语法失败，已回滚到: {backup}")
        log(f"[ERROR] {reason}")
        return 5

    log(f"[BACKUP] {backup}")
    log(f"[PATCHED] {target}")
    log("[OK] 语法检查通过")
    log("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
