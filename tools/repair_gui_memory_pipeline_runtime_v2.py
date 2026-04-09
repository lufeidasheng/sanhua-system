#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import re
import shutil
from datetime import datetime
from pathlib import Path


START_MARKER = "# === SANHUA_GUI_MEMORY_PIPELINE_V1_START ==="
END_MARKER = "# === SANHUA_GUI_MEMORY_PIPELINE_V1_END ==="
CALL_MARKER = "# SANHUA_GUI_MEMORY_PIPELINE_CALL"


HELPER_BLOCK = r'''
# === SANHUA_GUI_MEMORY_PIPELINE_V1_START ===
import json as _sanhua_gui_mem_json

_SANHUA_GUI_MEMORY_QUERY_HINTS = (
    "我是谁",
    "你记得我吗",
    "记得我",
    "我的名字",
    "我叫什么",
    "你认识我吗",
    "回忆刚才",
    "刚才我说了什么",
    "我刚才说了什么",
    "回忆一下",
)


def _sanhua_gui_mem_resolve_dispatcher(_aicore):
    if _aicore is None:
        return None

    _resolver = getattr(_aicore, "_resolve_dispatcher", None)
    if callable(_resolver):
        try:
            _d = _resolver()
            if _d is not None:
                return _d
        except Exception:
            pass

    for _name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        _d = getattr(_aicore, _name, None)
        if _d is not None:
            return _d

    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        if ACTION_MANAGER is not None:
            return ACTION_MANAGER
    except Exception:
        pass

    return None


def _sanhua_gui_mem_get_action_meta(_dispatcher, _action_name):
    if _dispatcher is None:
        return None

    _getter = getattr(_dispatcher, "get_action", None)
    if callable(_getter):
        try:
            return _getter(_action_name)
        except Exception:
            return None
    return None


def _sanhua_gui_mem_extract_callable(_action_meta):
    if _action_meta is None:
        return None

    for _name in ("func", "callable", "handler"):
        _fn = getattr(_action_meta, _name, None)
        if callable(_fn):
            return _fn

    if callable(_action_meta):
        return _action_meta

    return None


def _sanhua_gui_mem_call_action_meta(_action_name, _action_meta, **_kwargs):
    _fn = _sanhua_gui_mem_extract_callable(_action_meta)
    if not callable(_fn):
        return {"ok": False, "error": f"action_meta_not_callable:{_action_name}", "action": _action_name}

    _trials = [
        lambda: _fn(**_kwargs),
        lambda: _fn(context={}, **_kwargs),
        lambda: _fn(context=None, **_kwargs),
        lambda: _fn(kwargs=_kwargs),
        lambda: _fn(),
    ]

    _last_error = None
    for _trial in _trials:
        try:
            _result = _trial()
            return _result if isinstance(_result, dict) else {"result": _result}
        except TypeError as _e:
            _last_error = _e
            continue
        except Exception as _e:
            return {"ok": False, "error": str(_e), "action": _action_name}

    if _last_error is not None:
        return {"ok": False, "error": str(_last_error), "action": _action_name}

    return {"ok": False, "error": f"unknown_meta_call_error:{_action_name}", "action": _action_name}


def _sanhua_gui_mem_execute(_aicore, _action_name, **_kwargs):
    _dispatcher = _sanhua_gui_mem_resolve_dispatcher(_aicore)
    if _dispatcher is None:
        return {}

    # 1) 优先走 get_action(func)，避开 dispatcher.execute 的 context positional 注入
    _meta = _sanhua_gui_mem_get_action_meta(_dispatcher, _action_name)
    if _meta is not None:
        _result = _sanhua_gui_mem_call_action_meta(_action_name, _meta, **_kwargs)
        if isinstance(_result, dict) and not (
            _result.get("ok") is False and "action_meta_not_callable" in str(_result.get("error"))
        ):
            return _result

    # 2) 兜底才走 dispatcher.execute/call_action
    for _method_name in ("execute", "call_action"):
        _fn = getattr(_dispatcher, _method_name, None)
        if not callable(_fn):
            continue

        _trials = (
            lambda: _fn(_action_name, **_kwargs),
            lambda: _fn(_action_name, _kwargs),
            lambda: _fn(_action_name),
        )
        _last_error = None
        for _trial in _trials:
            try:
                _result = _trial()
                return _result if isinstance(_result, dict) else {"result": _result}
            except TypeError as _e:
                _last_error = _e
                continue
            except Exception as _e:
                return {"ok": False, "error": str(_e), "action": _action_name}

        if _last_error is not None:
            return {"ok": False, "error": str(_last_error), "action": _action_name}

    return {}


def _sanhua_gui_mem_extract_text(_value):
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
        ):
            _v = _value.get(_key)
            if isinstance(_v, str) and _v.strip():
                return _v

        _output = _value.get("output")
        if isinstance(_output, dict):
            return _sanhua_gui_mem_extract_text(_output)

        _result = _value.get("result")
        if isinstance(_result, dict):
            return _sanhua_gui_mem_extract_text(_result)

    try:
        return str(_value)
    except Exception:
        return ""


def _sanhua_gui_mem_normalize_match(_item):
    if not isinstance(_item, dict):
        return str(_item)

    _match_text = _item.get("match_text")
    if isinstance(_match_text, str) and _match_text.strip():
        return _match_text.strip()

    _content = _item.get("content")
    if isinstance(_content, dict):
        _inner = _content.get("content")
        if isinstance(_inner, str):
            return _inner.strip()
        if isinstance(_inner, dict):
            try:
                return _sanhua_gui_mem_json.dumps(_inner, ensure_ascii=False)
            except Exception:
                return str(_inner)
        try:
            return _sanhua_gui_mem_json.dumps(_content, ensure_ascii=False)
        except Exception:
            return str(_content)

    try:
        return _sanhua_gui_mem_json.dumps(_item, ensure_ascii=False)
    except Exception:
        return str(_item)


def _sanhua_gui_mem_collect_context(_aicore, _user_text, _limit=5):
    _query = str(_user_text or "").strip()
    _payload = {
        "identity": {},
        "recent_messages": [],
        "matches": [],
    }

    if not _query:
        return _payload

    _recall = _sanhua_gui_mem_execute(_aicore, "memory.recall", query=_query, limit=_limit)
    if isinstance(_recall, dict):
        for _item in (_recall.get("results") or []):
            _norm = _sanhua_gui_mem_normalize_match(_item)
            if _norm:
                _payload["matches"].append(_norm)

    _need_snapshot = any(_hint in _query for _hint in _SANHUA_GUI_MEMORY_QUERY_HINTS)
    if _need_snapshot:
        _snapshot = _sanhua_gui_mem_execute(_aicore, "memory.snapshot")
        if isinstance(_snapshot, dict):
            _snap = _snapshot.get("snapshot") or {}
            _persona = ((_snap.get("persona") or {}).get("user_profile") or {})
            _session = ((_snap.get("session_cache") or {}).get("active_session") or {})
            _recent = _session.get("recent_messages") or []

            _identity_candidate = {
                "name": _persona.get("name") or "",
                "aliases": _persona.get("aliases") or [],
                "notes": _persona.get("notes") or "",
                "project_focus": _persona.get("project_focus") or [],
                "stable_facts": _persona.get("stable_facts") or {},
            }

            _has_identity = any(
                [
                    str(_identity_candidate.get("name") or "").strip(),
                    any(str(x).strip() for x in (_identity_candidate.get("aliases") or [])),
                    str(_identity_candidate.get("notes") or "").strip(),
                    any(str(x).strip() for x in (_identity_candidate.get("project_focus") or [])),
                    any(str(v).strip() for v in (_identity_candidate.get("stable_facts") or {}).values()),
                ]
            )
            if _has_identity:
                _payload["identity"] = _identity_candidate

            _norm_recent = []
            for _m in _recent[-8:]:
                if not isinstance(_m, dict):
                    continue
                _role = str(_m.get("role") or "").strip() or "unknown"
                _content = str(_m.get("content") or "").strip()
                if _content:
                    _norm_recent.append({"role": _role, "content": _content})
            _payload["recent_messages"] = _norm_recent

    return _payload


def _sanhua_gui_mem_build_prompt(_user_text, _ctx):
    if not isinstance(_ctx, dict):
        return _user_text

    _lines = []
    _identity = _ctx.get("identity") or {}
    _recent = _ctx.get("recent_messages") or []
    _matches = _ctx.get("matches") or []

    if _identity:
        _name = str(_identity.get("name") or "").strip()
        _aliases = _identity.get("aliases") or []
        _notes = str(_identity.get("notes") or "").strip()
        _project_focus = _identity.get("project_focus") or []
        _stable_facts = _identity.get("stable_facts") or {}

        _lines.append("【稳定身份记忆】")
        if _name:
            _lines.append(f"- 用户名：{_name}")
        if _aliases:
            _lines.append(f"- 别名：{', '.join(str(x) for x in _aliases if str(x).strip())}")
        if _project_focus:
            _lines.append(f"- 项目重点：{', '.join(str(x) for x in _project_focus if str(x).strip())}")
        if _notes:
            _lines.append(f"- 备注：{_notes}")
        for _k, _v in _stable_facts.items():
            if str(_v).strip():
                _lines.append(f"- {_k}: {_v}")

    if _recent:
        _lines.append("【最近会话】")
        for _item in _recent[-8:]:
            _role = _item.get("role", "unknown")
            _content = _item.get("content", "")
            if _content:
                _lines.append(f"- {_role}: {_content}")

    if _matches:
        _lines.append("【相关记忆命中】")
        for _idx, _text in enumerate(_matches[:5], start=1):
            if _text:
                _lines.append(f"- 命中{_idx}: {_text}")

    if not _lines:
        return _user_text

    _memory_block = "\n".join(_lines).strip()
    return (
        "请把下面这些系统记忆当作高优先级参考事实。\n"
        "它们用于回答与用户身份、历史对话、刚才说过的话、长期偏好相关的问题。\n"
        "如果无关就忽略，不要硬编。\n\n"
        f"{_memory_block}\n\n"
        f"当前用户问题：\n{_user_text}"
    )


def _sanhua_gui_mem_append_chat(_aicore, _role, _content):
    _content = str(_content or "").strip()
    _role = str(_role or "").strip() or "user"
    if not _content:
        return {}
    return _sanhua_gui_mem_execute(
        _aicore,
        "memory.append_chat",
        role=_role,
        content=_content,
    )


def _sanhua_gui_mem_append_action(_aicore, _action_name, _status, _result_summary):
    return _sanhua_gui_mem_execute(
        _aicore,
        "memory.append_action",
        action_name=str(_action_name or "").strip() or "aicore.chat",
        status=str(_status or "").strip() or "success",
        result_summary=str(_result_summary or "").strip()[:500],
    )


def _sanhua_gui_mem_wrap_method(_aicore, _method_name):
    _orig = getattr(_aicore, _method_name, None)
    if not callable(_orig):
        return False

    if getattr(_orig, "_sanhua_gui_memory_wrapped", False):
        return False

    def _wrapped(_user_text, *args, **kwargs):
        if not isinstance(_user_text, str):
            return _orig(_user_text, *args, **kwargs)

        _plain = _user_text.strip()
        if not _plain:
            return _orig(_user_text, *args, **kwargs)

        try:
            _sanhua_gui_mem_append_chat(_aicore, "user", _plain)
        except Exception:
            pass

        try:
            _ctx = _sanhua_gui_mem_collect_context(_aicore, _plain)
        except Exception:
            _ctx = {}

        _augmented = _sanhua_gui_mem_build_prompt(_plain, _ctx)
        _result = _orig(_augmented, *args, **kwargs)
        _reply = _sanhua_gui_mem_extract_text(_result)

        try:
            if _reply.strip():
                _sanhua_gui_mem_append_chat(_aicore, "assistant", _reply)
        except Exception:
            pass

        try:
            _summary = (_reply or f"{_method_name}_done").strip()[:200]
            _sanhua_gui_mem_append_action(_aicore, f"aicore.{_method_name}", "success", _summary)
        except Exception:
            pass

        return _result

    setattr(_wrapped, "_sanhua_gui_memory_wrapped", True)
    setattr(_wrapped, "__wrapped__", _orig)
    setattr(_aicore, _method_name, _wrapped)
    return True


def _sanhua_gui_install_memory_pipeline(_aicore):
    if _aicore is None:
        return False

    if getattr(_aicore, "_sanhua_gui_memory_pipeline_installed", False):
        return False

    _installed = False
    for _name in ("chat", "ask"):
        try:
            _installed = _sanhua_gui_mem_wrap_method(_aicore, _name) or _installed
        except Exception as _e:
            print(f"⚠️ GUI memory pipeline wrap 失败: {_name} -> {_e}")

    setattr(_aicore, "_sanhua_gui_memory_pipeline_installed", True)

    if _installed:
        print("🧠 GUI memory pipeline installed")
    return _installed

# === SANHUA_GUI_MEMORY_PIPELINE_V1_END ===
'''


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    try:
        rel = target.resolve().relative_to(root.resolve())
        backup_path = backup_root / rel
    except Exception:
        backup_path = backup_root / target.name

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def render_diff(before: str, after: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after-patch)",
            lineterm="",
        )
    )


def replace_or_inject_helper_block(text: str) -> str:
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        flags=re.S,
    )
    block = HELPER_BLOCK.strip()

    if START_MARKER in text and END_MARKER in text:
        return pattern.sub(block, text, count=1)

    anchor = 'if __name__ == "__main__":'
    idx = text.find(anchor)
    if idx >= 0:
        return text[:idx] + block + "\n\n" + text[idx:]
    return text.rstrip() + "\n\n" + block + "\n"


def ensure_install_call(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    out: list[str] = []
    patched_refs: list[str] = []

    assign_patterns = [
        re.compile(
            r"^(?P<indent>\s*)(?P<lhs>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:[A-Za-z_][A-Za-z0-9_\.]*\.)?get_aicore_instance\s*\("
        ),
        re.compile(
            r"^(?P<indent>\s*)(?P<lhs>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:[A-Za-z_][A-Za-z0-9_\.]*\.)?ExtensibleAICore\s*\("
        ),
    ]

    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)

        matched_lhs = None
        matched_indent = ""
        for pattern in assign_patterns:
            m = pattern.match(line)
            if m:
                matched_lhs = m.group("lhs")
                matched_indent = m.group("indent")
                break

        if matched_lhs:
            already = False
            for la in lines[i + 1 : i + 4]:
                if CALL_MARKER in la or f"_sanhua_gui_install_memory_pipeline({matched_lhs})" in la:
                    already = True
                    break
            if not already:
                out.append(f"{matched_indent}_sanhua_gui_install_memory_pipeline({matched_lhs})  {CALL_MARKER}")
                patched_refs.append(matched_lhs)

        i += 1

    return "\n".join(out) + "\n", patched_refs


def patch_text(before: str) -> tuple[str, list[str]]:
    text = replace_or_inject_helper_block(before)
    text, refs = ensure_install_call(text)
    return text, refs


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 GUI memory pipeline 运行桥接（v2）")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("repair_gui_memory_pipeline_runtime_v2")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print(f"[ERROR] target not found: {target}")
        return 2

    before = read_text(target)
    after, refs = patch_text(before)

    if after == before:
        print("[SKIP] 无需修改")
        return 0

    print(f"[INFO] patched_refs: {refs if refs else '[]'}")
    diff_text = render_diff(before, after, target)
    print("[DIFF PREVIEW]")
    print(diff_text[:12000] if diff_text else "(none)")

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        return 0

    backup = make_backup(root, target)
    write_text(target, after)
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
