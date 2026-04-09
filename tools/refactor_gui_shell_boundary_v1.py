#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import re
import textwrap
from pathlib import Path


GUI_BRIDGE_INIT = r'''from .gui_memory_bridge import (
    append_action,
    append_chat,
    build_prompt,
    collect_context,
    display_is_polluted,
    execute,
    extract_text,
    install_memory_pipeline,
    sanitize_reply_for_writeback,
    try_local_memory_answer,
)
from .chat_orchestrator import GUIChatOrchestrator
from .alias_bootstrap import bootstrap_aliases, count_dispatcher_aliases
'''

GUI_MEMORY_BRIDGE = r'''#!/usr/bin/env python3
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


def resolve_dispatcher(aicore: Any):
    if aicore is None:
        return None

    resolver = getattr(aicore, "_resolve_dispatcher", None)
    if callable(resolver):
        try:
            d = resolver()
            if d is not None:
                return d
        except Exception:
            pass

    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        d = getattr(aicore, name, None)
        if d is not None:
            return d

    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        if ACTION_MANAGER is not None:
            return ACTION_MANAGER
    except Exception:
        pass

    return None


def get_action_meta(dispatcher: Any, action_name: str):
    if dispatcher is None:
        return None

    getter = getattr(dispatcher, "get_action", None)
    if callable(getter):
        try:
            return getter(action_name)
        except Exception:
            return None
    return None


def extract_callable(action_meta: Any):
    if action_meta is None:
        return None

    for name in ("func", "callable", "handler"):
        fn = getattr(action_meta, name, None)
        if callable(fn):
            return fn

    if callable(action_meta):
        return action_meta

    return None


def call_action_meta(action_name: str, action_meta: Any, **kwargs):
    fn = extract_callable(action_meta)
    if not callable(fn):
        return {
            "ok": False,
            "error": f"action_meta_not_callable:{action_name}",
            "action": action_name,
        }

    trials = [
        lambda: fn(**kwargs),
        lambda: fn(context={}, **kwargs),
        lambda: fn(context=None, **kwargs),
        lambda: fn(kwargs=kwargs),
        lambda: fn(),
    ]

    last_error = None
    for trial in trials:
        try:
            result = trial()
            return result if isinstance(result, dict) else {"result": result}
        except TypeError as e:
            last_error = e
            continue
        except Exception as e:
            return {"ok": False, "error": str(e), "action": action_name}

    if last_error is not None:
        return {"ok": False, "error": str(last_error), "action": action_name}

    return {"ok": False, "error": f"unknown_meta_call_error:{action_name}", "action": action_name}


def execute(aicore: Any, action_name: str, **kwargs):
    dispatcher = resolve_dispatcher(aicore)
    if dispatcher is None:
        return {}

    meta = get_action_meta(dispatcher, action_name)
    if meta is not None:
        result = call_action_meta(action_name, meta, **kwargs)
        if isinstance(result, dict) and not (
            result.get("ok") is False
            and "action_meta_not_callable" in str(result.get("error"))
        ):
            return result

    for method_name in ("execute", "call_action"):
        fn = getattr(dispatcher, method_name, None)
        if not callable(fn):
            continue

        trials = (
            lambda: fn(action_name, **kwargs),
            lambda: fn(action_name, kwargs),
            lambda: fn(action_name),
        )
        last_error = None
        for trial in trials:
            try:
                result = trial()
                return result if isinstance(result, dict) else {"result": result}
            except TypeError as e:
                last_error = e
                continue
            except Exception as e:
                return {"ok": False, "error": str(e), "action": action_name}

        if last_error is not None:
            return {"ok": False, "error": str(last_error), "action": action_name}

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
'''

CHAT_ORCHESTRATOR = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Callable, Optional

from .gui_memory_bridge import (
    append_action,
    append_chat,
    display_is_polluted,
    execute as mem_execute,
    extract_text,
    try_local_memory_answer,
)


class GUIChatOrchestrator:
    def __init__(
        self,
        ctx: Any,
        aicore: Any,
        action_caller: Callable[[str, dict], Any],
        list_actions: Callable[[], list],
        logger: Optional[Callable[[str], None]] = None,
        strip_protocol: Optional[Callable[[Any], str]] = None,
    ):
        self.ctx = ctx
        self.aicore = aicore
        self.action_caller = action_caller
        self.list_actions = list_actions
        self.logger = logger
        self.strip_protocol = strip_protocol or (lambda x: str(x or ""))

    def _log(self, text: str) -> None:
        if callable(self.logger):
            try:
                self.logger(text)
                return
            except Exception:
                pass
        print(text)

    def _extract_reply(self, obj: Any) -> str:
        try:
            text = extract_text(obj)
        except Exception:
            text = str(obj or "")
        text = self.strip_protocol(text)
        return str(text or "").strip()

    def _remember_local_turn(self, user_text: str, reply: str, kind: str) -> None:
        user_text = str(user_text or "").strip()
        reply = str(reply or "").strip()
        kind = str(kind or "").strip() or "local"
        ac = self.aicore

        if not reply:
            return

        try:
            need_append_user = True
            snapshot = mem_execute(ac, "memory.snapshot")
            if isinstance(snapshot, dict):
                snap = snapshot.get("snapshot") or {}
                session = ((snap.get("session_cache") or {}).get("active_session") or {})
                recent = session.get("recent_messages") or []
                for m in reversed(recent[-6:]):
                    if not isinstance(m, dict):
                        continue
                    if str(m.get("role") or "").strip() != "user":
                        continue
                    last_user = str(m.get("content") or "").strip()
                    if last_user == user_text:
                        need_append_user = False
                    break

            if need_append_user and user_text:
                append_chat(ac, "user", user_text)
        except Exception:
            pass

        try:
            append_chat(ac, "assistant", reply)
        except Exception:
            pass

        try:
            append_action(
                ac,
                f"gui.local_memory.{kind}",
                "success",
                reply[:200],
            )
        except Exception:
            pass

    def _try_local_memory(self, user_text: str) -> str:
        try:
            local = try_local_memory_answer(self.aicore, user_text)
        except Exception as e:
            self._log(f"⚠️ 本地记忆直答失败: {e}")
            return ""

        if local.get("ok"):
            reply = str(local.get("reply") or "").strip()
            kind = str(local.get("kind") or "local").strip()
            if reply:
                self._log(f"🧠 GUI local memory answer -> {kind}")
                self._remember_local_turn(user_text, reply, kind)
                return reply

        return ""

    def handle_chat(self, user_text: str) -> str:
        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\n"
            "1. 只用中文回答\n"
            "2. 直接给出最终答案\n"
            "3. 不要输出思考过程\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\n"
            "5. 不要包含任何分析、解释或内部思考\n"
            "6. 以纯文本形式输出"
        )

        local_reply = self._try_local_memory(user_text)
        if local_reply:
            self._log("⚡ chat short-circuit -> local memory")
            return local_reply

        try:
            if self.aicore is not None:
                for name in ("ask", "chat"):
                    fn = getattr(self.aicore, name, None)
                    if not callable(fn):
                        continue

                    self._log(f"🧠 chat route -> AICore.{name}")
                    raw = fn(user_text)
                    reply = self._extract_reply(raw)
                    if not reply:
                        continue

                    if display_is_polluted(reply):
                        self._log("🧼 GUI display sanitize -> polluted AICore reply blocked")
                        local_reply = self._try_local_memory(user_text)
                        if local_reply:
                            return local_reply
                        continue

                    return reply
        except RecursionError:
            self._log("❌ AICore 优先链失败: recursion detected")
        except Exception as e:
            self._log(f"❌ AICore 优先链失败: {e}")

        try:
            self._log("🤖 chat route -> ai.chat")
            res = self.action_caller(
                "ai.chat",
                {
                    "query": user_text,
                    "prompt": user_text,
                    "message": user_text,
                    "text": user_text,
                    "system_prompt": system_prompt,
                    "system": system_prompt,
                },
            )
            reply = self._extract_reply(res)
            if reply:
                if display_is_polluted(reply):
                    self._log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")
                    local_reply = self._try_local_memory(user_text)
                    if local_reply:
                        return local_reply
                else:
                    return reply
        except Exception as e:
            self._log(f"❌ ai.chat 失败: {e}")

        try:
            self._log("🤖 chat route -> action:aicore.chat")
            res = self.action_caller(
                "aicore.chat",
                {
                    "query": user_text,
                    "prompt": user_text,
                    "message": user_text,
                    "text": user_text,
                },
            )
            reply = self._extract_reply(res)
            if reply:
                if display_is_polluted(reply):
                    self._log("🧼 GUI display sanitize -> polluted action:aicore.chat reply blocked")
                    local_reply = self._try_local_memory(user_text)
                    if local_reply:
                        return local_reply
                else:
                    return reply
        except Exception as e:
            self._log(f"❌ aicore.chat 失败: {e}")

        local_reply = self._try_local_memory(user_text)
        if local_reply:
            return local_reply

        return "抱歉，我这次没有拿到有效回复。"
'''

ALIAS_BOOTSTRAP = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

try:
    from utils.alias_loader import load_aliases_from_yaml
except Exception:
    load_aliases_from_yaml = None  # type: ignore


def _log(logger: Optional[Callable[[str], None]], text: str) -> None:
    if callable(logger):
        try:
            logger(text)
            return
        except Exception:
            pass
    print(text)


def resolve_alias_files(root: Optional[str] = None) -> Tuple[Path, Path, str]:
    root_path = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    platform_key = sys.platform.lower()
    base = root_path / "config" / "aliases.yaml"
    plat = root_path / "config" / f"aliases.{platform_key}.yaml"
    return base, plat, platform_key


def count_dispatcher_aliases(dispatcher: Any) -> int:
    if dispatcher is None:
        return 0

    for attr in ("aliases", "_aliases", "alias_map", "_alias_map"):
        data = getattr(dispatcher, attr, None)
        if isinstance(data, dict):
            return len(data)

    return 0


def bootstrap_aliases(
    dispatcher: Any,
    logger: Optional[Callable[[str], None]] = None,
    root: Optional[str] = None,
    skip_if_present: bool = True,
) -> int:
    if dispatcher is None:
        _log(logger, "⚠️ dispatcher 不可用，跳过 aliases 加载")
        return 0

    base, plat, platform_key = resolve_alias_files(root=root)
    existing = count_dispatcher_aliases(dispatcher)

    if skip_if_present and existing > 0:
        _log(logger, f"🌸 aliases 已就绪：{existing} 条（platform={platform_key}）")
        return existing

    if not callable(load_aliases_from_yaml):
        _log(logger, "⚠️ alias_loader 不可用，无法加载 aliases")
        return existing

    total = 0
    try:
        if base.exists():
            total += int(load_aliases_from_yaml(str(base), dispatcher) or 0)
        if plat.exists():
            total += int(load_aliases_from_yaml(str(plat), dispatcher) or 0)
    except Exception as e:
        _log(logger, f"❌ alias 加载失败：{e}")
        return count_dispatcher_aliases(dispatcher)

    final_count = count_dispatcher_aliases(dispatcher)
    if final_count > 0:
        _log(logger, f"🌸 aliases loaded = {final_count} (platform={platform_key})")
        return final_count

    _log(
        logger,
        f"⚠️ aliases 未加载（未找到 {base.name} / {plat.name}，或 loader 返回 0）",
    )
    return max(total, existing, final_count)
'''


def ensure_file(path: Path, content: str, apply: bool) -> bool:
    content = textwrap.dedent(content).lstrip()
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = old != content
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return changed


def ensure_imports(src: str) -> str:
    if "from core.gui_bridge.gui_memory_bridge import install_memory_pipeline as gui_install_memory_pipeline" in src:
        return src

    marker = "from PyQt6.QtCore import Qt, QTimer\n"
    add = (
        "from core.gui_bridge.gui_memory_bridge import install_memory_pipeline as gui_install_memory_pipeline\n"
        "from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator\n"
        "from core.gui_bridge.alias_bootstrap import bootstrap_aliases as gui_bootstrap_aliases\n"
    )
    if marker in src:
        return src.replace(marker, marker + add, 1)

    raise RuntimeError("未找到 PyQt6.QtCore import 注入点")


def replace_once(src: str, old: str, new: str) -> str:
    if old not in src:
        return src
    return src.replace(old, new, 1)


def replace_method(src: str, method_name: str, new_block: str) -> str:
    pattern = re.compile(
        rf"(?ms)^    def {re.escape(method_name)}\(.*?(?=^    def |^# === |\Z)"
    )
    m = pattern.search(src)
    if not m:
        raise RuntimeError(f"未找到方法: {method_name}")
    return src[: m.start()] + textwrap.dedent(new_block).rstrip() + "\n\n" + src[m.end():]


def patch_gui_main(src: str) -> str:
    src = ensure_imports(src)

    src = replace_once(
        src,
        "        _sanhua_gui_install_memory_pipeline(self.ac)  # SANHUA_GUI_MEMORY_PIPELINE_CALL",
        "        gui_install_memory_pipeline(self.ac, logger=print)  # SANHUA_GUI_MEMORY_PIPELINE_CALL",
    )

    if "self.chat_orchestrator = GUIChatOrchestrator(" not in src:
        src = replace_once(
            src,
            "        self._init_ui()\n",
            (
                "        self._init_ui()\n\n"
                "        self.chat_orchestrator = GUIChatOrchestrator(\n"
                "            ctx=self.ctx,\n"
                "            aicore=self.ac,\n"
                "            action_caller=self._safe_call_action,\n"
                "            list_actions=self._list_actions,\n"
                "            logger=self.append_log,\n"
                "            strip_protocol=self._strip_llm_protocol,\n"
                "        )\n"
            ),
        )

    new_try_load_aliases = r'''
    def _try_load_aliases(self):
        try:
            count = gui_bootstrap_aliases(
                dispatcher=self.dispatcher,
                logger=self.append_log,
                root=str(project_root()),
                skip_if_present=True,
            )
            if count > 0:
                try:
                    setattr(self.ctx, "_aliases_loaded", True)
                except Exception:
                    pass
        except Exception as e:
            self.append_log(f"❌ alias 加载失败：{pretty_exc(e)}")
'''

    new_chat_method = r'''
    def _chat_via_actions(self, user_text: str) -> str:
        if not hasattr(self, "chat_orchestrator") or self.chat_orchestrator is None:
            self.chat_orchestrator = GUIChatOrchestrator(
                ctx=self.ctx,
                aicore=self.ac,
                action_caller=self._safe_call_action,
                list_actions=self._list_actions,
                logger=self.append_log,
                strip_protocol=self._strip_llm_protocol,
            )
        return self.chat_orchestrator.handle_chat(user_text)
'''

    src = replace_method(src, "_try_load_aliases", new_try_load_aliases)
    src = replace_method(src, "_chat_via_actions", new_chat_method)

    return src


def unified_diff_text(a: str, b: str, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            a.splitlines(True),
            b.splitlines(True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"
    if not gui_main.exists():
        raise SystemExit(f"找不到 gui_main.py: {gui_main}")

    print("=" * 96)
    print("refactor_gui_shell_boundary_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {gui_main}")

    files = {
        root / "core" / "gui_bridge" / "__init__.py": GUI_BRIDGE_INIT,
        root / "core" / "gui_bridge" / "gui_memory_bridge.py": GUI_MEMORY_BRIDGE,
        root / "core" / "gui_bridge" / "chat_orchestrator.py": CHAT_ORCHESTRATOR,
        root / "core" / "gui_bridge" / "alias_bootstrap.py": ALIAS_BOOTSTRAP,
    }

    any_changed = False
    for path, content in files.items():
        changed = ensure_file(path, content, apply=args.apply)
        print(f"[MODULE] {path.relative_to(root)} -> changed={changed}")
        any_changed = any_changed or changed

    before = gui_main.read_text(encoding="utf-8")
    after = patch_gui_main(before)
    changed_gui = before != after
    any_changed = any_changed or changed_gui

    print(f"[GUI] changed={changed_gui}")
    if changed_gui:
        diff = unified_diff_text(before, after, f"{gui_main} (before)", f"{gui_main} (after)")
        print("[DIFF PREVIEW]")
        print(diff[:12000])

    if args.apply and changed_gui:
        backup = gui_main.with_suffix(".py.bak_shell_boundary_v1")
        if not backup.exists():
            backup.write_text(before, encoding="utf-8")
            print(f"[BACKUP] {backup}")
        gui_main.write_text(after, encoding="utf-8")
        print(f"[PATCHED] {gui_main}")

    print("[RESULT]", "CHANGED" if any_changed else "NO_CHANGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
