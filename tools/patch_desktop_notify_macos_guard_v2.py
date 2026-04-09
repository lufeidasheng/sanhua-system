#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
from pathlib import Path


TARGET_REL = "modules/desktop_notify/module.py"
PATCH_MARKER = "SANHUA_DESKTOP_NOTIFY_DARWIN_MONKEYPATCH_V2"

PATCH_BLOCK = r'''
# === SANHUA_DESKTOP_NOTIFY_DARWIN_MONKEYPATCH_V2 START ===
def _sanhua_dt_is_darwin():
    try:
        import sys
        return sys.platform == "darwin"
    except Exception:
        return False


def _sanhua_dt_log(level: str, message: str):
    for _name in ("logger", "log", "LOGGER", "_logger"):
        _obj = globals().get(_name)
        if _obj is not None and hasattr(_obj, level):
            try:
                getattr(_obj, level)(message)
                return
            except Exception:
                pass
    try:
        print(message)
    except Exception:
        pass


def _sanhua_dt_console_notify(title: str, message: str):
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


def _sanhua_dt_notify_macos(title: str, message: str):
    try:
        import subprocess

        safe_title = str(title).replace('"', '\\"')
        safe_message = str(message).replace('"', '\\"')
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], check=False)
        return {
            "ok": True,
            "backend": "macos_osascript",
            "title": title,
            "message": message,
        }
    except Exception:
        return _sanhua_dt_console_notify(title, message)


def _sanhua_dt_extract_title_message(args, kwargs):
    title = kwargs.get("title")
    message = kwargs.get("message")

    if title is None and len(args) >= 1:
        title = args[0]
    if message is None and len(args) >= 2:
        message = args[1]

    if title is None:
        title = "三花聚顶"
    if message is None:
        if len(args) == 1 and "title" not in kwargs:
            message = str(args[0])
            title = "三花聚顶"
        else:
            message = ""

    return str(title), str(message)


def _sanhua_dt_install_darwin_patch():
    if not _sanhua_dt_is_darwin():
        return

    _cls = globals().get("DesktopNotifyModule")
    if not isinstance(_cls, type):
        _sanhua_dt_log("warning", "desktop_notify: 未找到 DesktopNotifyModule，跳过 Darwin monkey patch")
        return

    def _sanhua_dt_backend_bootstrap(self, *args, **kwargs):
        try:
            self._notify_backend = "macos_osascript"
            self.notify_backend = "macos_osascript"
            self._notify_impl = _sanhua_dt_notify_macos
        except Exception:
            pass
        return {
            "ok": True,
            "backend": "macos_osascript",
            "reason": "darwin_monkey_patch",
        }

    def _sanhua_dt_send(self, *args, **kwargs):
        title, message = _sanhua_dt_extract_title_message(args, kwargs)
        return _sanhua_dt_notify_macos(title, message)

    # 1) 覆盖常见初始化方法，阻断 gi/libnotify 链路
    for _name in (
        "_init_notify_backend",
        "init_notify_backend",
        "_setup_notify_backend",
        "setup_notify_backend",
        "_init_notifier",
        "init_notifier",
        "_init_notify",
        "init_notify",
        "_ensure_notify_backend",
        "ensure_notify_backend",
    ):
        try:
            setattr(_cls, _name, _sanhua_dt_backend_bootstrap)
        except Exception:
            pass

    # 2) 覆盖 setup，避免 setup 内继续触发 gi/libnotify
    try:
        setattr(_cls, "setup", _sanhua_dt_backend_bootstrap)
    except Exception:
        pass

    # 3) 覆盖常见通知发送方法
    for _name in (
        "notify",
        "_notify",
        "send_notification",
        "_send_notification",
        "show_notification",
        "_show_notification",
        "push_notification",
        "_push_notification",
    ):
        try:
            setattr(_cls, _name, _sanhua_dt_send)
        except Exception:
            pass

    _sanhua_dt_log("info", "desktop_notify: Darwin monkey patch active (osascript/console fallback)")

try:
    _sanhua_dt_install_darwin_patch()
except Exception as _e:
    try:
        print(f"desktop_notify: Darwin monkey patch install failed: {_e}")
    except Exception:
        pass
# === SANHUA_DESKTOP_NOTIFY_DARWIN_MONKEYPATCH_V2 END ===
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

    patched = text.rstrip() + "\n\n\n" + PATCH_BLOCK + "\n"
    return patched, None


def main() -> int:
    parser = argparse.ArgumentParser(description="为 desktop_notify 增加 macOS 末尾猴补丁，绕开 GI/libnotify 噪音")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / TARGET_REL

    log("=" * 100)
    log("patch_desktop_notify_macos_guard_v2")
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
