#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
patch_gui_runtime_aicore_bridge_v1.py

目标：
1. 在 entry/gui_entry/gui_main.py 中，给 self.runtime 安装 AICore bridge
2. 强制 GUI runtime 的 chat/ask/generate/infer/run/request 等入口优先走 self.ac.ask/self.ac.chat
3. 打印明确链路日志：
   [GUI_SEND]
   [GUI_ROUTE]
   [GUI_REPLY]
4. 保留原始 runtime 作为兜底，不把 GUI 直接打残

用法：
  python3 tools/patch_gui_runtime_aicore_bridge_v1.py --root "/Users/lufei/Desktop/聚核助手2.0"
  python3 tools/patch_gui_runtime_aicore_bridge_v1.py --root "/Users/lufei/Desktop/聚核助手2.0" --apply
"""

from __future__ import annotations

import argparse
import difflib
import shutil
from datetime import datetime
from pathlib import Path


PATCH_CALL_MARKER = "SANHUA_GUI_RUNTIME_AICORE_BRIDGE_CALL"
PATCH_BLOCK_START = "# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_START ==="
PATCH_BLOCK_END = "# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_END ==="


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_backup(root: Path, target: Path) -> Path:
    rel = target.relative_to(root)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def build_helper_block() -> str:
    return rf"""
{PATCH_BLOCK_START}

def _sanhua_gui_bridge_extract_text(_value):
    if _value is None:
        return ""

    if isinstance(_value, str):
        return _value

    if isinstance(_value, dict):
        for _key in (
            "reply",
            "answer",
            "content",
            "text",
            "message",
            "assistant_reply",
            "response",
            "final_answer",
            "result",
        ):
            _v = _value.get(_key)
            if isinstance(_v, str) and _v.strip():
                return _v

        _output = _value.get("output")
        if isinstance(_output, dict):
            return _sanhua_gui_bridge_extract_text(_output)

    try:
        return str(_value)
    except Exception:
        return ""


def _sanhua_gui_bridge_pick_aicore_method(_ac):
    if _ac is None:
        return None, None

    for _name in ("ask", "chat"):
        _fn = getattr(_ac, _name, None)
        if callable(_fn):
            return _name, _fn

    return None, None


def _sanhua_gui_bridge_call_aicore(_ac, _user_text, *args, **kwargs):
    _method_name, _fn = _sanhua_gui_bridge_pick_aicore_method(_ac)
    if not callable(_fn):
        raise RuntimeError("aicore.ask/chat not available")

    _plain = str(_user_text or "").strip()
    if not _plain:
        raise RuntimeError("empty_user_text")

    print(f"[GUI_SEND] raw_input={{_plain[:200]}}")
    print(f"[GUI_ROUTE] target=AICore.{{_method_name}}")

    _last_error = None
    _trials = [
        lambda: _fn(_plain, *args, **kwargs),
        lambda: _fn(_plain),
        lambda: _fn(prompt=_plain),
        lambda: _fn(text=_plain),
    ]

    for _trial in _trials:
        try:
            _result = _trial()
            _reply = _sanhua_gui_bridge_extract_text(_result)
            if _reply.strip():
                print(f"[GUI_REPLY] source=AICore.{{_method_name}}")
            else:
                print(f"[GUI_REPLY] source=AICore.{{_method_name}} (empty_text)")
            return _result
        except TypeError as _e:
            _last_error = _e
            continue

    if _last_error is not None:
        raise _last_error
    raise RuntimeError("unknown_aicore_bridge_error")


def _sanhua_gui_bridge_wrap_runtime_method(_runtime, _ac, _method_name):
    _orig = getattr(_runtime, _method_name, None)
    if not callable(_orig):
        return False

    if getattr(_orig, "_sanhua_gui_runtime_bridge_wrapped", False):
        return False

    def _wrapped(*args, **kwargs):
        if not args:
            return _orig(*args, **kwargs)

        _user_text = args[0]

        if _ac is None:
            return _orig(*args, **kwargs)

        if not isinstance(_user_text, str):
            return _orig(*args, **kwargs)

        if not _user_text.strip():
            return _orig(*args, **kwargs)

        try:
            return _sanhua_gui_bridge_call_aicore(_ac, _user_text, *args[1:], **kwargs)
        except Exception as _e:
            print(f"⚠️ GUI runtime AICore bridge fallback: {{_method_name}} -> {{_e}}")
            return _orig(*args, **kwargs)

    setattr(_wrapped, "_sanhua_gui_runtime_bridge_wrapped", True)
    setattr(_wrapped, "__wrapped__", _orig)
    setattr(_runtime, _method_name, _wrapped)
    return True


def _sanhua_gui_install_runtime_aicore_bridge(_runtime, _ac):
    if _runtime is None or _ac is None:
        return False

    if getattr(_runtime, "_sanhua_gui_runtime_bridge_installed", False):
        return False

    _installed = False

    try:
        setattr(_runtime, "ac", _ac)
    except Exception:
        pass

    for _name in ("chat", "ask", "generate", "infer", "run", "request"):
        try:
            _installed = _sanhua_gui_bridge_wrap_runtime_method(_runtime, _ac, _name) or _installed
        except Exception as _e:
            print(f"⚠️ install runtime bridge failed: {{_name}} -> {{_e}}")

    setattr(_runtime, "_sanhua_gui_runtime_bridge_installed", True)

    if _installed:
        print("🧭 GUI runtime AICore bridge installed")

    return _installed

{PATCH_BLOCK_END}
"""


def insert_helper_block(text: str) -> tuple[str, bool]:
    if PATCH_BLOCK_START in text and PATCH_BLOCK_END in text:
        return text, False

    anchor_candidates = [
        "\nif __name__ == \"__main__\":",
        "\nif __name__ == '__main__':",
    ]

    insert_at = -1
    for anchor in anchor_candidates:
        idx = text.find(anchor)
        if idx != -1:
            insert_at = idx
            break

    if insert_at == -1:
        raise RuntimeError("anchor_not_found:main_guard")

    block = "\n" + build_helper_block().rstrip() + "\n\n"
    patched = text[:insert_at] + block + text[insert_at:]
    return patched, True


def insert_runtime_bridge_call(text: str) -> tuple[str, bool]:
    if PATCH_CALL_MARKER in text:
        return text, False

    anchor = "self.runtime = ModelRuntime(self.ctx, ac=self.ac)"
    idx = text.find(anchor)
    if idx == -1:
        raise RuntimeError("anchor_not_found:runtime_init")

    replacement = (
        anchor
        + "\n"
        + "        _sanhua_gui_install_runtime_aicore_bridge(self.runtime, self.ac)  # "
        + PATCH_CALL_MARKER
    )
    patched = text.replace(anchor, replacement, 1)
    return patched, True


def unified_diff_preview(before: str, after: str, path: Path, limit: int = 220) -> str:
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after-patch)",
            lineterm="",
        )
    )
    if len(diff) > limit:
        diff = diff[:limit] + ["... [diff truncated]"]
    return "\n".join(diff)


def patch_text(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    text2, changed_block = insert_helper_block(text)
    if changed_block:
        notes.append("inserted_helper_block")

    text3, changed_call = insert_runtime_bridge_call(text2)
    if changed_call:
        notes.append("inserted_runtime_bridge_call")

    return text3, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="为 GUI runtime 强制安装 AICore bridge")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("patch_gui_runtime_aicore_bridge_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 2

    before = read_text(target)

    try:
        after, notes = patch_text(before)
        compile(after, str(target), "exec")
    except Exception as e:
        print(f"[ERROR] patch 失败: {e}")
        return 3

    print(f"[INFO] patched_refs: {notes}")
    print("[DIFF PREVIEW]")
    print(unified_diff_preview(before, after, target))

    if not args.apply:
        print("[PREVIEW] 补丁可应用，且语法通过")
        return 0

    backup = make_backup(root, target)
    write_text(target, after)

    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
