#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

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

_SANHUA_GUI_MEMORY_ECHO_PREFIXES = (
    "FAKE_AICORE_REPLY::",
    "FAKE_AICORE_CHAT_REPLY::",
)

_POLLUTION_MARKERS = (
    "请把下面这些系统记忆当作高优先级参考事实",
    "下面是与当前问题强相关的记忆摘要",
    "它们用于回答与用户身份、历史对话、刚才说过的话、长期偏好相关的问题",
    "当前用户问题：",
    "用户问题：",
    "【稳定身份记忆】",
    "【最近会话】",
    "【相关记忆命中】",
    "【用户画像】",
    "【最近用户消息】",
    "【相关记忆摘要】",
    "FAKE_AICORE_REPLY::",
    "FAKE_AICORE_CHAT_REPLY::",
)


def _log(logger: Optional[Callable[[str], None]], text: str) -> None:
    if callable(logger):
        try:
            logger(text)
            return
        except Exception:
            pass
    print(text)


def extract_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, dict):
            for key in (
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
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    return v

        for key in (
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
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v

        output = value.get("output")
        if isinstance(output, dict):
            return extract_text(output)

    try:
        return str(value)
    except Exception:
        return ""


def strip_echo_prefix(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    for prefix in _SANHUA_GUI_MEMORY_ECHO_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def compact_text(text: Any, limit: Optional[int] = None) -> str:
    text = str(text or "").replace("\u3000", " ").strip()
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = " ".join(text.split())

    if limit is not None:
        try:
            limit = int(limit)
        except Exception:
            limit = None

        if limit and limit > 0 and len(text) > limit:
            text = text[: max(limit - 1, 1)].rstrip() + "…"

    return text.strip()


def text_key(text: Any) -> str:
    text = compact_text(text).lower()
    if not text:
        return ""
    return " ".join(text.split())


def display_is_polluted(text: Any) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _POLLUTION_MARKERS)


def is_augmented_echo(reply_text: Any, augmented_prompt: Any) -> bool:
    reply_text = compact_text(strip_echo_prefix(reply_text))
    augmented_prompt = compact_text(augmented_prompt)

    if not reply_text or not augmented_prompt:
        return False

    if reply_text == augmented_prompt:
        return True

    if reply_text.startswith(augmented_prompt):
        return True

    if augmented_prompt in reply_text and len(augmented_prompt) >= 80:
        return True

    return False


def sanitize_reply_for_writeback(plain_user_text: Any, augmented_prompt: Any, reply_obj: Any) -> str:
    reply_text = extract_text(reply_obj)
    reply_text = strip_echo_prefix(reply_text)
    reply_text = compact_text(reply_text)

    if not reply_text:
        return ""

    if is_augmented_echo(reply_text, augmented_prompt):
        return ""

    if display_is_polluted(reply_text):
        return ""

    return reply_text[:4000]


def resolve_context(aicore: Any):
    if aicore is None:
        return None

    for name in ("context", "ctx"):
        ctx = getattr(aicore, name, None)
        if ctx is not None:
            return ctx

    return None


def execute(aicore: Any, action: str, **kwargs):
    context = resolve_context(aicore)
    if context is not None:
        caller = getattr(context, "call_action", None)
        if callable(caller):
            try:
                result = caller(action, params=kwargs)
                return result if isinstance(result, dict) else {"result": result}
            except Exception as e:
                return {"ok": False, "error": str(e), "action": action}

    return {}


def append_chat(aicore: Any, role: str, content: str):
    content = str(content or "").strip()
    role = str(role or "").strip() or "user"
    if not content:
        return {}
    return execute(
        aicore,
        "memory.append_chat",
        role=role,
        content=content,
    )


def append_action(aicore: Any, action_name: str, status: str, result_summary: str):
    return execute(
        aicore,
        "memory.append_action",
        action_name=str(action_name or "").strip() or "aicore.chat",
        status=str(status or "").strip() or "success",
        result_summary=compact_text(result_summary, limit=200),
    )


def normalize_match(item: Any) -> str:
    if not isinstance(item, dict):
        text = compact_text(item, limit=96)
        return "" if display_is_polluted(text) else text

    match_text = item.get("match_text")
    if isinstance(match_text, str) and match_text.strip():
        match_text = compact_text(match_text, limit=96)
        return "" if display_is_polluted(match_text) else match_text

    content = item.get("content")
    if isinstance(content, dict):
        inner = content.get("content")
        if isinstance(inner, str):
            inner = compact_text(inner, limit=96)
            return "" if display_is_polluted(inner) else inner
        if isinstance(inner, dict):
            try:
                text = json.dumps(inner, ensure_ascii=False)
            except Exception:
                text = str(inner)
            text = compact_text(text, limit=96)
            return "" if display_is_polluted(text) else text

    try:
        text = json.dumps(item, ensure_ascii=False)
    except Exception:
        text = str(item)

    text = compact_text(text, limit=96)
    return "" if display_is_polluted(text) else text


def push_unique(arr: List[str], seen: set, text: Any, limit: int = 160, max_items: Optional[int] = None) -> bool:
    text = compact_text(text, limit=limit)
    if not text:
        return False

    if display_is_polluted(text):
        return False

    key = text_key(text)
    if not key or key in seen:
        return False

    arr.append(text)
    seen.add(key)

    if max_items is not None:
        try:
            max_items = int(max_items)
        except Exception:
            max_items = None

        if max_items is not None and max_items >= 0 and len(arr) > max_items:
            del arr[max_items:]

    return True


def identity_name_ok(name: Any) -> bool:
    name = compact_text(name, limit=24)
    if not name:
        return False

    bad_exact = {
        "谁", "我", "你", "他", "她", "它",
        "用户", "user", "unknown", "none", "null",
        "姓名", "名字", "我是谁", "你是谁",
    }
    if name.lower() in bad_exact or name in bad_exact:
        return False

    if len(name) > 24:
        return False

    bad_parts = ("当前用户问题", "用户问题", "记忆", "摘要", "recent", "identity")
    if any(x in name for x in bad_parts):
        return False

    return True


def pick_identity_name(persona: Dict[str, Any], stable_facts: Dict[str, Any], aliases: List[str]) -> str:
    candidates = [
        persona.get("name"),
        stable_facts.get("identity.name"),
        *list(aliases or []),
    ]
    for c in candidates:
        c = compact_text(c, limit=24)
        if identity_name_ok(c):
            return c
    return ""


def collect_context(aicore: Any, user_text: str, limit: int = 5) -> Dict[str, Any]:
    query = compact_text(user_text, limit=120)
    payload = {
        "identity": {},
        "recent_messages": [],
        "matches": [],
    }

    if not query:
        return payload

    try:
        limit = max(int(limit or 5), 5)
    except Exception:
        limit = 5

    query_key = text_key(query)

    recall = execute(aicore, "memory.recall", query=query, limit=max(limit, 8))
    match_seen = set()
    if isinstance(recall, dict):
        results = recall.get("results") or recall.get("items") or []
        for item in results:
            norm = normalize_match(item)
            norm = compact_text(norm, limit=96)
            if not norm:
                continue
            if text_key(norm) == query_key:
                continue
            push_unique(payload["matches"], match_seen, norm, limit=96, max_items=3)

    need_snapshot = (
        any(hint in query for hint in _SANHUA_GUI_MEMORY_QUERY_HINTS)
        or "回忆" in query
        or "刚才" in query
        or "记住" in query
    )
    if not need_snapshot:
        return payload

    snapshot = execute(aicore, "memory.snapshot")
    if not isinstance(snapshot, dict):
        return payload

    snap = snapshot.get("snapshot") or {}
    persona = ((snap.get("persona") or {}).get("user_profile") or {})
    session = ((snap.get("session_cache") or {}).get("active_session") or {})
    recent = session.get("recent_messages") or []

    alias_seen = set()
    aliases = []
    for x in (persona.get("aliases") or []):
        x = compact_text(x, limit=24)
        if not x:
            continue
        k = text_key(x)
        if not k or k in alias_seen:
            continue
        alias_seen.add(k)
        aliases.append(x)
        if len(aliases) >= 3:
            break

    focus_seen = set()
    project_focus = []
    for x in (persona.get("project_focus") or []):
        x = compact_text(x, limit=32)
        if not x:
            continue
        k = text_key(x)
        if not k or k in focus_seen:
            continue
        focus_seen.add(k)
        project_focus.append(x)
        if len(project_focus) >= 4:
            break

    stable_src = persona.get("stable_facts") or {}
    stable_facts = {}
    for k in (
        "identity.name",
        "system.primary_project",
        "response.preference",
        "memory_architecture_focus",
    ):
        v = compact_text(stable_src.get(k), limit=80)
        if v:
            stable_facts[k] = v

    resolved_name = pick_identity_name(persona, stable_facts, aliases)

    clean_aliases = []
    alias_seen_2 = set()
    for a in aliases:
        a = compact_text(a, limit=24)
        if not identity_name_ok(a):
            continue
        k = text_key(a)
        if not k or k in alias_seen_2:
            continue
        alias_seen_2.add(k)
        clean_aliases.append(a)

    if resolved_name:
        resolved_key = text_key(resolved_name)
        clean_aliases = [x for x in clean_aliases if text_key(x) != resolved_key]

    identity_candidate = {
        "name": resolved_name,
        "aliases": clean_aliases[:3],
        "notes": compact_text(persona.get("notes"), limit=120),
        "project_focus": project_focus,
        "stable_facts": stable_facts,
    }

    has_identity = any(
        [
            str(identity_candidate.get("name") or "").strip(),
            any(str(x).strip() for x in (identity_candidate.get("aliases") or [])),
            str(identity_candidate.get("notes") or "").strip(),
            any(str(x).strip() for x in (identity_candidate.get("project_focus") or [])),
            any(str(v).strip() for v in (identity_candidate.get("stable_facts") or {}).values()),
        ]
    )
    if has_identity:
        payload["identity"] = identity_candidate

    recent_seen = set()
    recent_rows = []
    for m in recent[-12:]:
        if not isinstance(m, dict):
            continue

        role = str(m.get("role") or "").strip() or "unknown"
        content = compact_text(m.get("content"), limit=120)

        if role != "user":
            continue
        if not content:
            continue
        if display_is_polluted(content):
            continue
        if text_key(content) == query_key:
            continue

        row_key = f"{role}:{text_key(content)}"
        if row_key in recent_seen:
            continue

        recent_seen.add(row_key)
        recent_rows.append({"role": "user", "content": content})

    payload["recent_messages"] = recent_rows[-4:]
    return payload


def build_prompt(user_text: str, ctx: Dict[str, Any]) -> str:
    user_text = str(user_text or "").strip()
    if not user_text:
        return user_text

    if not isinstance(ctx, dict):
        return user_text

    sections = []

    identity = ctx.get("identity") or {}
    if identity:
        lines = []
        name = compact_text(identity.get("name"), limit=24)
        aliases = [str(x).strip() for x in (identity.get("aliases") or []) if str(x).strip()]
        project_focus = [str(x).strip() for x in (identity.get("project_focus") or []) if str(x).strip()]
        notes = compact_text(identity.get("notes"), limit=96)
        stable_facts = identity.get("stable_facts") or {}

        if name:
            lines.append(f"- 用户名：{name}")
        if aliases:
            lines.append(f"- 别名：{', '.join(aliases[:3])}")
        if project_focus:
            lines.append(f"- 项目重点：{', '.join(project_focus[:4])}")

        primary_project = compact_text(stable_facts.get("system.primary_project"), limit=40)
        if primary_project:
            lines.append(f"- 核心项目：{primary_project}")

        preference = compact_text(stable_facts.get("response.preference"), limit=60)
        if preference:
            lines.append(f"- 回复偏好：{preference}")

        if notes:
            lines.append(f"- 备注：{notes}")

        if lines:
            sections.append("【用户画像】\n" + "\n".join(lines))

    recent_lines = []
    recent_seen = set()
    for item in (ctx.get("recent_messages") or [])[-4:]:
        if not isinstance(item, dict):
            continue
        content = compact_text(item.get("content"), limit=88)
        if not content:
            continue
        k = text_key(content)
        if not k or k in recent_seen:
            continue
        recent_seen.add(k)
        recent_lines.append(f"- {content}")

    if recent_lines:
        sections.append("【最近用户消息】\n" + "\n".join(recent_lines))

    match_lines = []
    match_seen = set(recent_seen)
    user_key = text_key(user_text)
    for text in (ctx.get("matches") or [])[:6]:
        text = compact_text(text, limit=88)
        if not text:
            continue
        if display_is_polluted(text):
            continue
        k = text_key(text)
        if not k or k == user_key or k in match_seen:
            continue
        match_seen.add(k)
        match_lines.append(f"- {text}")
        if len(match_lines) >= 3:
            break

    if match_lines:
        sections.append("【相关记忆摘要】\n" + "\n".join(match_lines))

    if not sections:
        return user_text

    memory_block = "\n\n".join(sections).strip()
    return (
        "下面是与当前问题强相关的记忆摘要，仅在相关时参考；"
        "不要逐字复述摘要，也不要把摘要原样输出给用户。\n"
        "请直接用自然中文给出最终答复。\n\n"
        f"{memory_block}\n\n"
        f"用户问题：\n{user_text}"
    )


def local_memory_identity_reply(identity: Dict[str, Any]) -> str:
    if not isinstance(identity, dict):
        return ""

    name = str(identity.get("name") or "").strip()
    aliases = [str(x).strip() for x in (identity.get("aliases") or []) if str(x).strip()]
    project_focus = [str(x).strip() for x in (identity.get("project_focus") or []) if str(x).strip()]
    notes = str(identity.get("notes") or "").strip()
    stable_facts = identity.get("stable_facts") or {}

    parts = []
    if name:
        parts.append(f"你是{name}。")
    if aliases:
        parts.append(f"我记得你的别名有：{', '.join(aliases)}。")
    if project_focus:
        parts.append(f"你当前重点在：{', '.join(project_focus[:4])}。")
    if notes:
        parts.append(notes)

    primary_project = str(stable_facts.get("system.primary_project") or "").strip()
    if primary_project:
        parts.append(f"你的核心项目是《{primary_project}》。")

    preference = str(stable_facts.get("response.preference") or "").strip()
    if preference:
        parts.append(f"你的偏好是：{preference}。")

    return "".join(parts).strip()


def local_memory_recent_reply(recent: List[Dict[str, Any]], current_user_text: str) -> str:
    current_user_text = str(current_user_text or "").strip()
    user_msgs = []

    for m in (recent or []):
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "").strip() != "user":
            continue
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if content == current_user_text:
            continue
        user_msgs.append(content)

    if not user_msgs:
        return ""

    user_msgs = user_msgs[-3:]
    lines = [f"{idx}. {txt}" for idx, txt in enumerate(user_msgs, start=1)]
    return "你刚才说过：\n" + "\n".join(lines)


def try_local_memory_answer(aicore: Any, user_text: str) -> Dict[str, Any]:
    plain = str(user_text or "").strip()
    if not plain:
        return {"ok": False, "reason": "empty_user_text"}

    try:
        ctx = collect_context(aicore, plain, limit=8)
    except Exception as e:
        return {"ok": False, "reason": f"context_error:{e}"}

    identity = (ctx or {}).get("identity") or {}
    recent = (ctx or {}).get("recent_messages") or []

    identity_hints = (
        "我是谁",
        "你记得我吗",
        "记得我吗",
        "你认识我吗",
        "我叫什么",
        "我的名字",
    )
    recall_hints = (
        "帮我回忆刚才我说了什么",
        "刚才我说了什么",
        "我刚才说了什么",
        "回忆刚才",
        "回忆一下",
        "你记得刚才我说了什么",
    )

    if any(hint in plain for hint in identity_hints):
        reply = local_memory_identity_reply(identity)
        if reply:
            return {"ok": True, "kind": "identity", "reply": reply}

    if any(hint in plain for hint in recall_hints):
        reply = local_memory_recent_reply(recent, plain)
        if reply:
            return {"ok": True, "kind": "recent_recall", "reply": reply}

    return {"ok": False, "reason": "no_local_answer"}


def wrap_method(aicore: Any, method_name: str, logger: Optional[Callable[[str], None]] = None) -> bool:
    orig = getattr(aicore, method_name, None)
    if not callable(orig):
        return False

    if getattr(orig, "_sanhua_gui_memory_wrapped_v2", False):
        return False

    depth_attr = "_sanhua_gui_memory_pipeline_depth"

    def wrapped(user_text, *args, **kwargs):
        if not isinstance(user_text, str):
            return orig(user_text, *args, **kwargs)

        plain = user_text.strip()
        if not plain:
            return orig(user_text, *args, **kwargs)

        depth = int(getattr(aicore, depth_attr, 0) or 0)
        if depth > 0:
            return orig(user_text, *args, **kwargs)

        setattr(aicore, depth_attr, depth + 1)
        try:
            try:
                append_chat(aicore, "user", plain)
            except Exception:
                pass

            try:
                ctx = collect_context(aicore, plain)
            except Exception:
                ctx = {}

            augmented = build_prompt(plain, ctx)
            result = orig(augmented, *args, **kwargs)

            sanitized_reply = sanitize_reply_for_writeback(plain, augmented, result)
            raw_reply = extract_text(result)

            try:
                if sanitized_reply.strip():
                    append_chat(aicore, "assistant", sanitized_reply)
                elif str(raw_reply or "").strip():
                    _log(logger, "⚠️ GUI memory pipeline: polluted assistant reply skipped")
            except Exception:
                pass

            try:
                summary = (sanitized_reply or f"{method_name}_done").strip()[:200]
                append_action(aicore, f"aicore.{method_name}", "success", summary)
            except Exception:
                pass

            return result
        finally:
            current = int(getattr(aicore, depth_attr, 1) or 1)
            setattr(aicore, depth_attr, max(current - 1, 0))

    setattr(wrapped, "_sanhua_gui_memory_wrapped_v2", True)
    setattr(wrapped, "__wrapped__", orig)
    setattr(aicore, method_name, wrapped)
    return True


def install_memory_pipeline(aicore: Any, logger: Optional[Callable[[str], None]] = None) -> bool:
    if aicore is None:
        return False

    if getattr(aicore, "_sanhua_gui_memory_pipeline_installed_v2", False):
        return False

    installed = False
    for name in ("ask", "chat"):
        try:
            installed = wrap_method(aicore, name, logger=logger) or installed
        except Exception as e:
            _log(logger, f"⚠️ GUI memory pipeline wrap 失败: {name} -> {e}")

    setattr(aicore, "_sanhua_gui_memory_pipeline_installed_v2", True)
    if installed:
        _log(logger, "🧠 GUI memory pipeline installed")
    return installed
