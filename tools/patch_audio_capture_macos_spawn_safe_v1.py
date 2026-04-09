#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import time
from pathlib import Path


PATCH_MARK = "SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_START"


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_diff(old: str, new: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after-patch)",
            lineterm="",
        )
    )


def build_patch_block() -> str:
    return r'''

# === SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_START ===
try:
    import os as _sanhua_os
    import sys as _sanhua_sys

    def _sanhua_audio_log(level, msg):
        _logger = globals().get("logger") or globals().get("log")
        if _logger is not None:
            _fn = getattr(_logger, level, None)
            if callable(_fn):
                try:
                    _fn(msg)
                    return
                except Exception:
                    pass
        print(msg)

    if "AudioCapture" in globals():
        _SANHUA_ORIG_AUDIOCAPTURE_START = getattr(AudioCapture, "start", None)

        def _sanhua_audio_capture_start_safe(self, *args, **kwargs):
            # 手动总开关：GUI 测试时可关闭
            if _sanhua_os.environ.get("SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS") == "1":
                self.started = False
                setattr(self, "degraded_reason", "disabled_by_env")
                _sanhua_audio_log(
                    "warning",
                    "audio_capture 已按环境变量禁用进程启动（SANHUA_DISABLE_AUDIO_CAPTURE_PROCESS=1）"
                )
                return False

            if _sanhua_sys.platform != "darwin":
                if callable(_SANHUA_ORIG_AUDIOCAPTURE_START):
                    return _SANHUA_ORIG_AUDIOCAPTURE_START(self, *args, **kwargs)
                return False

            try:
                if callable(_SANHUA_ORIG_AUDIOCAPTURE_START):
                    return _SANHUA_ORIG_AUDIOCAPTURE_START(self, *args, **kwargs)
                return False
            except TypeError as _e:
                _msg = str(_e)
                if "_thread._local" in _msg or "cannot pickle" in _msg:
                    self.started = False
                    setattr(self, "_process", None)
                    setattr(self, "degraded_reason", "spawn_pickle_thread_local")
                    _sanhua_audio_log(
                        "warning",
                        "audio_capture 在 macOS 下触发 spawn/pickle 问题，已自动降级跳过子进程启动"
                    )
                    return False
                raise
            except Exception as _e:
                # 只对 Darwin 启动阶段做软降级，避免 GUI 被拖死
                self.started = False
                setattr(self, "_process", None)
                setattr(self, "degraded_reason", f"darwin_start_degraded:{_e}")
                _sanhua_audio_log(
                    "warning",
                    f"audio_capture macOS 启动降级：{_e}"
                )
                return False

        AudioCapture.start = _sanhua_audio_capture_start_safe

except Exception as _sanhua_audio_capture_patch_error:
    print(f"⚠️ audio_capture macOS spawn patch init failed: {_sanhua_audio_capture_patch_error}")
# === SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_END ===
'''


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 audio_capture 在 macOS 下的 spawn 崩溃")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    ap.add_argument("--report-json", default="", help="报告输出路径")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "audio_capture" / "module.py"
    if not target.exists():
        print(f"[ERROR] 文件不存在: {target}")
        return 2

    old = safe_read(target)
    changed = False
    new = old
    notes = []

    if PATCH_MARK not in old:
        new = old.rstrip() + "\n" + build_patch_block().strip("\n") + "\n"
        changed = True
        notes.append("已追加 audio_capture macOS spawn 安全补丁")
    else:
        notes.append("SKIP: 已存在 audio_capture macOS spawn 安全补丁")

    diff_text = make_diff(old, new, target)

    out_path = (
        Path(args.report_json).resolve()
        if args.report_json
        else root / "audit_output" / "patch_audio_capture_macos_spawn_safe_v1_report.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backup_root = None
    if args.apply and changed:
        backup_root = root / "audit_output" / "fix_backups" / time.strftime("%Y%m%d_%H%M%S")
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / "modules" / "audio_capture" / "module.py"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
        write_text(target, new)

    report = {
        "ok": True,
        "root": str(root),
        "apply": bool(args.apply),
        "target": str(target),
        "changed": changed,
        "notes": notes,
        "diff_preview": diff_text[:20000],
        "backup_root": str(backup_root) if backup_root else None,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 100)
    print("patch_audio_capture_macos_spawn_safe_v1")
    print("=" * 100)
    print(f"root    : {root}")
    print(f"apply   : {args.apply}")
    print(f"changed : {changed}")
    for n in notes:
        print(f"note    : {n}")
    if diff_text:
        print("-" * 100)
        print(diff_text[:8000])
    print("-" * 100)
    print(f"report_json : {out_path}")
    if backup_root:
        print(f"backup_root : {backup_root}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
