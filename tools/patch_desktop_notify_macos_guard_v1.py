#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
from pathlib import Path


TARGET_REL = "modules/desktop_notify/module.py"
PATCH_MARKER = "SANHUA_DARWIN_NOTIFY_GUARD_V1"


PATCH_BLOCK = r'''
# === SANHUA_DARWIN_NOTIFY_GUARD_V1 START ===
def _sanhua_is_darwin():
    try:
        import sys
        return sys.platform == "darwin"
    except Exception:
        return False


def _sanhua_console_notify(title: str, message: str):
    try:
        print(f"[desktop_notify:fallback] {title}: {message}")
    except Exception:
        pass
    return {
        "ok": True,
        "backend": "console_fallback",
        "title": title,
        "message": message,
    }


def _sanhua_notify_macos(title: str, message: str):
    try:
        import subprocess
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], check=False)
        return {
            "ok": True,
            "backend": "macos_osascript",
            "title": title,
            "message": message,
        }
    except Exception:
        return _sanhua_console_notify(title, message)
# === SANHUA_DARWIN_NOTIFY_GUARD_V1 END ===
'''.strip("\n")


def log(msg=""):
    print(msg)


def safe_read(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def backup_file(root: Path, target: Path) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / str(target).lstrip(os.sep)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def patch_text(text: str):
    if PATCH_MARKER in text:
        return text, "already_patched"

    # 1) 注入 helper block
    insert_anchor = 'logger = logging.getLogger(__name__)'
    if insert_anchor in text:
        text = text.replace(insert_anchor, insert_anchor + "\n\n" + PATCH_BLOCK, 1)
    else:
        return None, "anchor_not_found:logger"

    # 2) 让 Darwin 直接走 osascript / console fallback，跳过 gi/libnotify
    patterns = [
        (
            '        try:\n'
            '            import gi\n'
            '            gi.require_version("Notify", "0.7")\n'
            '            from gi.repository import Notify\n',
            '        try:\n'
            '            if _sanhua_is_darwin():\n'
            '                self._notify_backend = "macos_osascript"\n'
            '                self._notify_impl = _sanhua_notify_macos\n'
            '                return\n'
            '\n'
            '            import gi\n'
            '            gi.require_version("Notify", "0.7")\n'
            '            from gi.repository import Notify\n',
        ),
        (
            '            logger.warning(f"libnotify 不可用，将降级为控制台输出: {e}")\n'
            '            self._notify_backend = "console"\n'
            '            self._notify_impl = None\n',
            '            if _sanhua_is_darwin():\n'
            '                logger.info("desktop_notify: Darwin 平台使用 osascript/console fallback")\n'
            '                self._notify_backend = "macos_osascript"\n'
            '                self._notify_impl = _sanhua_notify_macos\n'
            '            else:\n'
            '                logger.warning(f"libnotify 不可用，将降级为控制台输出: {e}")\n'
            '                self._notify_backend = "console"\n'
            '                self._notify_impl = _sanhua_console_notify\n',
        ),
        (
            '        if self._notify_impl:\n'
            '            self._notify_impl(title, message)\n'
            '        else:\n'
            '            print(f"[桌面通知降级] {title}: {message}")\n',
            '        if self._notify_impl:\n'
            '            return self._notify_impl(title, message)\n'
            '        return _sanhua_console_notify(title, message)\n',
        ),
    ]

    for old, new in patterns:
        if old in text:
            text = text.replace(old, new, 1)

    return text, None


def main() -> int:
    parser = argparse.ArgumentParser(description="为 desktop_notify 增加 macOS 保护分支，避免 GI/libnotify 噪音")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / TARGET_REL

    log("=" * 100)
    log("patch_desktop_notify_macos_guard_v1")
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

    if err:
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
