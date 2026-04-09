#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
from datetime import datetime
from pathlib import Path


SCRIPT_NAME = "patch_gui_memory_short_circuit_user_writeback_v1"


def hr():
    print("=" * 96)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    out = backup_root / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def compile_check(target: Path, content: str) -> None:
    compile(content, str(target), "exec")


def patch_source(src: str) -> tuple[str, bool]:
    changed = False

    old_block = """        def _remember_local_answer(_reply: str, _kind: str):
            _reply = str(_reply or "").strip()
            _kind = str(_kind or "").strip() or "local"
            if not _reply:
                return

            try:
                _sanhua_gui_mem_append_chat(getattr(self, "ac", None), "assistant", _reply)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_action(
                    getattr(self, "ac", None),
                    f"gui.local_memory.{_kind}",
                    "success",
                    _reply[:200],
                )
            except Exception:
                pass

        def _try_local_memory() -> str:
            try:
                _local = _sanhua_gui_try_local_memory_answer(getattr(self, "ac", None), user_text)
            except Exception as _e:
                self.append_log(f"⚠️ 本地记忆直答失败: {_e}")
                return ""

            if _local.get("ok"):
                _reply = str(_local.get("reply") or "").strip()
                _kind = str(_local.get("kind") or "local").strip()
                if _reply:
                    self.append_log(f"🧠 GUI local memory answer -> {_kind}")
                    _remember_local_answer(_reply, _kind)
                    return _reply
            return """""

    new_block = """        def _remember_local_turn(_user_text: str, _reply: str, _kind: str):
            _user_text = str(_user_text or "").strip()
            _reply = str(_reply or "").strip()
            _kind = str(_kind or "").strip() or "local"
            _ac = getattr(self, "ac", None)

            if not _reply:
                return

            # short-circuit 路径不会经过 AICore wrapper，因此需要手动补 user turn
            try:
                _need_append_user = True
                _snapshot = _sanhua_gui_mem_execute(_ac, "memory.snapshot")
                if isinstance(_snapshot, dict):
                    _snap = _snapshot.get("snapshot") or {}
                    _session = ((_snap.get("session_cache") or {}).get("active_session") or {})
                    _recent = _session.get("recent_messages") or []
                    for _m in reversed(_recent[-6:]):
                        if not isinstance(_m, dict):
                            continue
                        if str(_m.get("role") or "").strip() != "user":
                            continue
                        _last_user = str(_m.get("content") or "").strip()
                        if _last_user == _user_text:
                            _need_append_user = False
                        break

                if _need_append_user and _user_text:
                    _sanhua_gui_mem_append_chat(_ac, "user", _user_text)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_chat(_ac, "assistant", _reply)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_action(
                    _ac,
                    f"gui.local_memory.{_kind}",
                    "success",
                    _reply[:200],
                )
            except Exception:
                pass

        def _try_local_memory() -> str:
            try:
                _local = _sanhua_gui_try_local_memory_answer(getattr(self, "ac", None), user_text)
            except Exception as _e:
                self.append_log(f"⚠️ 本地记忆直答失败: {_e}")
                return ""

            if _local.get("ok"):
                _reply = str(_local.get("reply") or "").strip()
                _kind = str(_local.get("kind") or "local").strip()
                if _reply:
                    self.append_log(f"🧠 GUI local memory answer -> {_kind}")
                    _remember_local_turn(user_text, _reply, _kind)
                    return _reply
            return """""

    if old_block in src:
        src = src.replace(old_block, new_block, 1)
        changed = True

    return src, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    hr()
    print(SCRIPT_NAME)
    hr()
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target not found")
        return 1

    before = read_text(target)
    after, changed = patch_source(before)

    try:
        compile_check(target, after)
    except Exception as e:
        print(f"[ERROR] compile failed: {e}")
        return 1

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"--- {target} (before)",
            tofile=f"+++ {target} (after)",
            n=3,
        )
    )

    print(f"[INFO] changed: {changed}")
    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff)
    else:
        print("[INFO] no diff")

    if not args.apply:
        print("[PREVIEW] 补丁可应用，且语法通过")
        hr()
        return 0

    backup = make_backup(root, target)
    write_text(target, after)
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    hr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
