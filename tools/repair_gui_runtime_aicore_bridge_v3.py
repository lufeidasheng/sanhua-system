#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import shutil
from datetime import datetime
from pathlib import Path


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


def build_block() -> str:
    return r'''
# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_START ===

import inspect as _sanhua_gui_bridge_inspect


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

    print(f"[GUI_SEND] raw_input={_plain[:200]}")
    print(f"[GUI_ROUTE] target=AICore.{_method_name}")

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
                print(f"[GUI_REPLY] source=AICore.{_method_name}")
            else:
                print(f"[GUI_REPLY] source=AICore.{_method_name} (empty_text)")
            return _result
        except TypeError as _e:
            _last_error = _e
            continue

    if _last_error is not None:
        raise _last_error
    raise RuntimeError("unknown_aicore_bridge_error")


def _sanhua_gui_bridge_declared_callable_names(_obj):
    _names = []
    if _obj is None:
        return _names

    _cls = getattr(_obj, "__class__", None)
    _cls_dict = getattr(_cls, "__dict__", {}) or {}

    for _name, _raw in _cls_dict.items():
        if not _name or _name.startswith("_"):
            continue

        try:
            _bound = getattr(_obj, _name, None)
        except Exception:
            continue

        if callable(_bound):
            _names.append(_name)

    return sorted(set(_names))


def _sanhua_gui_bridge_is_signal_like(_attr):
    if _attr is None:
        return False

    if hasattr(_attr, "connect") and hasattr(_attr, "emit"):
        if not (
            _sanhua_gui_bridge_inspect.ismethod(_attr)
            or _sanhua_gui_bridge_inspect.isfunction(_attr)
        ):
            return True

    return False


def _sanhua_gui_bridge_should_skip(_name):
    if not _name:
        return True

    _exact_skip = {
        "start",
        "stop",
        "close",
        "show",
        "hide",
        "refresh",
        "refresh_async",
        "update",
        "setup",
        "init",
        "initialize",
        "destroy",
        "cleanup",
        "shutdown",
        "get_status",
        "set_backend",
        "set_model",
        "blockSignals",
        "childEvent",
        "children",
        "connectNotify",
        "customEvent",
        "deleteLater",
        "destroyed",
        "disconnect",
        "disconnectNotify",
        "dumpObjectInfo",
        "dumpObjectTree",
        "dynamicPropertyNames",
        "event",
        "eventFilter",
        "findChild",
        "findChildren",
        "inherits",
        "installEventFilter",
        "isQuickItemType",
        "isSignalConnected",
        "isWidgetType",
        "isWindowType",
        "killTimer",
        "metaObject",
        "moveToThread",
        "objectName",
        "objectNameChanged",
        "parent",
        "property",
        "pyqtConfigure",
        "receivers",
        "removeEventFilter",
        "sender",
        "senderSignalIndex",
        "setObjectName",
        "setParent",
        "setProperty",
        "signalsBlocked",
        "startTimer",
        "status_changed",
        "thread",
        "timerEvent",
        "tr",
    }
    if _name in _exact_skip:
        return True

    _prefix_skip = (
        "set_",
        "get_",
        "load_",
        "save_",
        "refresh_",
        "update_",
        "paint",
        "resize",
        "mouse",
        "key",
        "wheel",
        "drag",
        "drop",
        "focus",
        "timer",
    )
    return _name.startswith(_prefix_skip)


def _sanhua_gui_bridge_candidate_method_names(_runtime):
    _declared = _sanhua_gui_bridge_declared_callable_names(_runtime)

    _preferred = (
        "reply_turn",
        "run_turn",
        "chat",
        "ask",
        "generate",
        "infer",
        "run",
        "request",
        "submit",
        "send_message",
        "process_text",
        "handle_text",
        "query",
    )

    _hints = (
        "chat",
        "ask",
        "reply",
        "message",
        "query",
        "prompt",
        "text",
        "turn",
        "send",
    )

    _candidates = []

    for _name in _declared:
        if _sanhua_gui_bridge_should_skip(_name):
            continue

        try:
            _attr = getattr(_runtime, _name, None)
        except Exception:
            continue

        if _sanhua_gui_bridge_is_signal_like(_attr):
            continue

        if not (
            _sanhua_gui_bridge_inspect.ismethod(_attr)
            or _sanhua_gui_bridge_inspect.isfunction(_attr)
        ):
            continue

        _lname = _name.lower()
        if _name in _preferred or any(_hint in _lname for _hint in _hints):
            _candidates.append(_name)

    _ordered = []
    for _name in _preferred:
        if _name in _candidates and _name not in _ordered:
            _ordered.append(_name)

    for _name in _candidates:
        if _name not in _ordered:
            _ordered.append(_name)

    return _declared, _ordered


def _sanhua_gui_bridge_wrap_runtime_method(_runtime, _ac, _method_name):
    _orig = getattr(_runtime, _method_name, None)
    if not callable(_orig):
        return False

    if getattr(_orig, "_sanhua_gui_runtime_bridge_wrapped", False):
        return False

    def _wrapped(*args, **kwargs):
        if _ac is None:
            return _orig(*args, **kwargs)

        if not args:
            return _orig(*args, **kwargs)

        _first = args[0]
        if not isinstance(_first, str):
            return _orig(*args, **kwargs)

        if not _first.strip():
            return _orig(*args, **kwargs)

        try:
            return _sanhua_gui_bridge_call_aicore(_ac, _first, *args[1:], **kwargs)
        except Exception as _e:
            print(f"⚠️ GUI runtime AICore bridge fallback: {_method_name} -> {_e}")
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

    try:
        setattr(_runtime, "ac", _ac)
    except Exception:
        pass

    _declared, _candidates = _sanhua_gui_bridge_candidate_method_names(_runtime)
    print(
        f"🧭 GUI runtime bridge probe: "
        f"class={_runtime.__class__.__name__} declared_callables={_declared} candidates={_candidates}"
    )

    _wrapped = []
    for _name in _candidates:
        try:
            if _sanhua_gui_bridge_wrap_runtime_method(_runtime, _ac, _name):
                _wrapped.append(_name)
        except Exception as _e:
            print(f"⚠️ install runtime bridge failed: {_name} -> {_e}")

    setattr(_runtime, "_sanhua_gui_runtime_bridge_installed", True)
    setattr(_runtime, "_sanhua_gui_runtime_bridge_wrapped_names", list(_wrapped))

    if _wrapped:
        print(f"🧭 GUI runtime AICore bridge installed: {_wrapped}")
        return True

    print("⚠️ GUI runtime AICore bridge installed: []")
    return False

# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_END ===
'''.lstrip()


def replace_block(text: str) -> tuple[str, bool]:
    start = text.find(PATCH_BLOCK_START)
    end = text.find(PATCH_BLOCK_END)
    if start == -1 or end == -1:
        raise RuntimeError("runtime_bridge_block_not_found")

    end = end + len(PATCH_BLOCK_END)
    new_block = build_block().rstrip()
    patched = text[:start] + new_block + text[end:]
    return patched, patched != text


def unified_diff_preview(before: str, after: str, path: Path, limit: int = 240) -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 GUI runtime AICore bridge v3（严格候选版）")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("repair_gui_runtime_aicore_bridge_v3")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 2

    before = read_text(target)

    try:
        after, changed = replace_block(before)
        compile(after, str(target), "exec")
    except Exception as e:
        print(f"[ERROR] repair failed: {e}")
        return 3

    print(f"[INFO] changed: {changed}")
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
