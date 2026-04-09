#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import py_compile
import re
import shutil
from pathlib import Path

TITLE = "patch_gui_memory_writeback_sanitize_v1"


HELPER_BLOCK = r'''
_SANHUA_GUI_MEMORY_POLLUTION_MARKERS = (
    "请把下面这些系统记忆当作高优先级参考事实",
    "它们用于回答与用户身份、历史对话、刚才说过的话、长期偏好相关的问题",
    "当前用户问题：",
    "【稳定身份记忆】",
    "【最近会话】",
    "【相关记忆命中】",
)

_SANHUA_GUI_MEMORY_ECHO_PREFIXES = (
    "FAKE_AICORE_REPLY::",
    "FAKE_AICORE_CHAT_REPLY::",
)


def _sanhua_gui_mem_strip_echo_prefix(_text):
    _text = str(_text or "").strip()
    if not _text:
        return ""

    for _prefix in _SANHUA_GUI_MEMORY_ECHO_PREFIXES:
        if _text.startswith(_prefix):
            return _text[len(_prefix):].strip()
    return _text


def _sanhua_gui_mem_compact_text(_text):
    _text = str(_text or "").strip()
    if not _text:
        return ""
    _text = _text.replace("\r\n", "\n").replace("\r", "\n")
    _text = re.sub(r"[ \t]+", " ", _text)
    _text = re.sub(r"\n{3,}", "\n\n", _text)
    return _text.strip()


def _sanhua_gui_mem_is_polluted_text(_text):
    _text = _sanhua_gui_mem_compact_text(_text)
    if not _text:
        return False

    _hit_count = 0
    for _marker in _SANHUA_GUI_MEMORY_POLLUTION_MARKERS:
        if _marker in _text:
            _hit_count += 1

    if _hit_count >= 2:
        return True

    if "当前用户问题：" in _text and "【稳定身份记忆】" in _text:
        return True

    if len(_text) > 800 and "请把下面这些系统记忆当作高优先级参考事实" in _text:
        return True

    return False


def _sanhua_gui_mem_is_augmented_echo(_reply_text, _augmented_prompt):
    _reply_text = _sanhua_gui_mem_compact_text(_sanhua_gui_mem_strip_echo_prefix(_reply_text))
    _augmented_prompt = _sanhua_gui_mem_compact_text(_augmented_prompt)

    if not _reply_text or not _augmented_prompt:
        return False

    if _reply_text == _augmented_prompt:
        return True

    if _reply_text.startswith(_augmented_prompt):
        return True

    if _augmented_prompt in _reply_text and len(_augmented_prompt) >= 80:
        return True

    return False


def _sanhua_gui_mem_sanitize_reply_for_writeback(_plain_user_text, _augmented_prompt, _reply_obj):
    _reply_text = _sanhua_gui_mem_extract_text(_reply_obj)
    _reply_text = _sanhua_gui_mem_strip_echo_prefix(_reply_text)
    _reply_text = _sanhua_gui_mem_compact_text(_reply_text)

    if not _reply_text:
        return ""

    if _sanhua_gui_mem_is_augmented_echo(_reply_text, _augmented_prompt):
        return ""

    if _sanhua_gui_mem_is_polluted_text(_reply_text):
        return ""

    return _reply_text[:4000]
'''.strip("\n")


NEW_NORMALIZE_MATCH = r'''
def _sanhua_gui_mem_normalize_match(_item):
    if not isinstance(_item, dict):
        _text = str(_item)
        if _sanhua_gui_mem_is_polluted_text(_text):
            return ""
        return _text

    _match_text = _item.get("match_text")
    if isinstance(_match_text, str) and _match_text.strip():
        _match_text = _match_text.strip()
        if _sanhua_gui_mem_is_polluted_text(_match_text):
            return ""
        return _match_text

    _content = _item.get("content")
    if isinstance(_content, dict):
        _inner = _content.get("content")
        if isinstance(_inner, str):
            _inner = _inner.strip()
            if _sanhua_gui_mem_is_polluted_text(_inner):
                return ""
            return _inner
        if isinstance(_inner, dict):
            try:
                _text = _sanhua_gui_mem_json.dumps(_inner, ensure_ascii=False)
            except Exception:
                _text = str(_inner)
            if _sanhua_gui_mem_is_polluted_text(_text):
                return ""
            return _text
        try:
            _text = _sanhua_gui_mem_json.dumps(_content, ensure_ascii=False)
        except Exception:
            _text = str(_content)
        if _sanhua_gui_mem_is_polluted_text(_text):
            return ""
        return _text

    try:
        _text = _sanhua_gui_mem_json.dumps(_item, ensure_ascii=False)
    except Exception:
        _text = str(_item)

    if _sanhua_gui_mem_is_polluted_text(_text):
        return ""
    return _text
'''.strip("\n")


NEW_COLLECT_CONTEXT = r'''
def _sanhua_gui_mem_collect_context(_aicore, _user_text, _limit=5):
    _query = str(_user_text or '').strip()
    _payload = {
        "identity": {},
        "recent_messages": [],
        "matches": [],
    }

    if not _query:
        return _payload

    _recall = _sanhua_gui_mem_execute(_aicore, "memory.recall", query=_query, limit=_limit)
    if isinstance(_recall, dict):
        for _item in (_recall.get('results') or []):
            _norm = _sanhua_gui_mem_normalize_match(_item)
            if _norm:
                _payload['matches'].append(_norm)

    _need_snapshot = any(_hint in _query for _hint in _SANHUA_GUI_MEMORY_QUERY_HINTS)
    if _need_snapshot:
        _snapshot = _sanhua_gui_mem_execute(_aicore, "memory.snapshot")
        if isinstance(_snapshot, dict):
            _snap = _snapshot.get('snapshot') or {}
            _persona = ((_snap.get('persona') or {}).get('user_profile') or {})
            _session = ((_snap.get('session_cache') or {}).get('active_session') or {})
            _recent = _session.get('recent_messages') or []

            _identity_candidate = {
                'name': _persona.get('name') or '',
                'aliases': _persona.get('aliases') or [],
                'notes': _persona.get('notes') or '',
                'project_focus': _persona.get('project_focus') or [],
                'stable_facts': _persona.get('stable_facts') or {},
            }

            _has_identity = any([
                str(_identity_candidate.get('name') or '').strip(),
                any(str(x).strip() for x in (_identity_candidate.get('aliases') or [])),
                str(_identity_candidate.get('notes') or '').strip(),
                any(str(x).strip() for x in (_identity_candidate.get('project_focus') or [])),
                any(str(v).strip() for v in (_identity_candidate.get('stable_facts') or {}).values()),
            ])
            if _has_identity:
                _payload['identity'] = _identity_candidate

            _norm_recent = []
            for _m in _recent[-8:]:
                if not isinstance(_m, dict):
                    continue

                _role = str(_m.get('role') or '').strip() or 'unknown'
                _content = str(_m.get('content') or '').strip()
                if not _content:
                    continue

                if _role == 'assistant' and _sanhua_gui_mem_is_polluted_text(_content):
                    continue

                _norm_recent.append({'role': _role, 'content': _content})

            _payload['recent_messages'] = _norm_recent

    return _payload
'''.strip("\n")


NEW_WRAP_METHOD = r'''
def _sanhua_gui_mem_wrap_method(_aicore, _method_name):
    _orig = getattr(_aicore, _method_name, None)
    if not callable(_orig):
        return False

    if getattr(_orig, '_sanhua_gui_memory_wrapped', False):
        return False

    def _wrapped(_user_text, *args, **kwargs):
        if not isinstance(_user_text, str):
            return _orig(_user_text, *args, **kwargs)

        _plain = _user_text.strip()
        if not _plain:
            return _orig(_user_text, *args, **kwargs)

        try:
            _sanhua_gui_mem_append_chat(_aicore, 'user', _plain)
        except Exception:
            pass

        try:
            _ctx = _sanhua_gui_mem_collect_context(_aicore, _plain)
        except Exception:
            _ctx = {}

        _augmented = _sanhua_gui_mem_build_prompt(_plain, _ctx)
        _result = _orig(_augmented, *args, **kwargs)

        _reply = _sanhua_gui_mem_extract_text(_result)
        _sanitized_reply = _sanhua_gui_mem_sanitize_reply_for_writeback(_plain, _augmented, _result)

        try:
            if _sanitized_reply.strip():
                _sanhua_gui_mem_append_chat(_aicore, 'assistant', _sanitized_reply)
            elif _reply.strip():
                print('⚠️ GUI memory pipeline: polluted assistant reply skipped')
        except Exception:
            pass

        try:
            _summary = (_sanitized_reply or f'{_method_name}_done').strip()[:200]
            _sanhua_gui_mem_append_action(_aicore, f'aicore.{_method_name}', 'success', _summary)
        except Exception:
            pass

        return _result

    setattr(_wrapped, '_sanhua_gui_memory_wrapped', True)
    setattr(_wrapped, '__wrapped__', _orig)
    setattr(_aicore, _method_name, _wrapped)
    return True
'''.strip("\n")


def make_backup(root: Path, target: Path) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def replace_top_level_func(text: str, func_name: str, new_block: str) -> str:
    pattern = rf"^def {re.escape(func_name)}\([^\n]*\):\n[\s\S]*?(?=^def [A-Za-z_][A-Za-z0-9_]*\(|\Z)"
    new_text, count = re.subn(pattern, new_block + "\n\n", text, count=1, flags=re.M)
    if count != 1:
        raise RuntimeError(f"replace_failed:{func_name}")
    return new_text


def apply_patch(text: str) -> str:
    if "# === SANHUA_GUI_MEMORY_PIPELINE_V1_START ===" not in text:
        raise RuntimeError("memory_pipeline_block_not_found")

    if "def _sanhua_gui_mem_sanitize_reply_for_writeback(" not in text:
        anchor = "def _sanhua_gui_mem_normalize_match("
        if anchor not in text:
            raise RuntimeError("anchor_not_found:_sanhua_gui_mem_normalize_match")
        text = text.replace(anchor, HELPER_BLOCK + "\n\n\n" + anchor, 1)

    text = replace_top_level_func(text, "_sanhua_gui_mem_normalize_match", NEW_NORMALIZE_MATCH)
    text = replace_top_level_func(text, "_sanhua_gui_mem_collect_context", NEW_COLLECT_CONTEXT)
    text = replace_top_level_func(text, "_sanhua_gui_mem_wrap_method", NEW_WRAP_METHOD)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print(TITLE)
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    old_text = target.read_text(encoding="utf-8")
    new_text = apply_patch(old_text)

    if new_text == old_text:
        print("[INFO] no_change")
        print("=" * 96)
        return 0

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        print("=" * 96)
        return 0

    backup = make_backup(root, target)
    target.write_text(new_text, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)

    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
