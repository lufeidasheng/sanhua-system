#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _safe_json_preview(obj: Any, max_chars: int = 220) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(obj)
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def _resolve_aicore(aicore: Any = None) -> Any:
    if aicore is not None:
        return aicore

    root = _project_root_from_here()
    _ensure_sys_path(root)
    os.chdir(root)

    from core.aicore.aicore import get_aicore_instance  # noqa
    return get_aicore_instance()


def _resolve_dispatcher(dispatcher: Any = None, aicore: Any = None) -> Any:
    if dispatcher is not None:
        return dispatcher

    aicore = _resolve_aicore(aicore)

    resolver = getattr(aicore, "_resolve_dispatcher", None)
    if callable(resolver):
        try:
            obj = resolver()
            if obj is not None:
                return obj
        except Exception:
            pass

    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        try:
            obj = getattr(aicore, name, None)
            if obj is not None:
                return obj
        except Exception:
            continue

    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER  # noqa
        if ACTION_MANAGER is not None:
            return ACTION_MANAGER
    except Exception:
        pass

    return None


def _ctx_value(context: Optional[Dict[str, Any]], kwargs: Dict[str, Any], key: str, default: Any = None) -> Any:
    if key in kwargs and kwargs.get(key) is not None:
        return kwargs.get(key)
    if isinstance(context, dict) and key in context and context.get(key) is not None:
        return context.get(key)
    return default


def _ensure_default_session(aicore: Any) -> None:
    fn = getattr(aicore, "_ensure_default_session", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass


def _manual_search_from_snapshot(aicore: Any, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    snapshot_fn = getattr(aicore, "memory_snapshot", None)
    if not callable(snapshot_fn):
        return []

    try:
        snap = snapshot_fn() or {}
    except Exception:
        return []

    long_term = (((snap.get("long_term") or {}).get("memories")) or [])
    q = str(query or "").strip().lower()
    if not q:
        return []

    out: List[Dict[str, Any]] = []
    for item in long_term:
        try:
            match_text = json.dumps(item.get("content", item), ensure_ascii=False, sort_keys=True)
        except Exception:
            match_text = str(item)

        if q in match_text.lower():
            out.append({
                "content": item,
                "match_text": match_text,
            })
            if len(out) >= limit:
                break

    return out


def action_memory_health(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()
    mm = getattr(aicore, "memory_manager", None)

    if mm is None:
        return {
            "ok": False,
            "error": "memory_manager_not_ready",
            "reason": "memory_manager_not_ready",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_health",
        }

    try:
        if hasattr(mm, "health_check") and callable(mm.health_check):
            data = mm.health_check()
        else:
            storage_dir = str((_project_root_from_here() / "data" / "memory").resolve())
            data = {
                "ok": True,
                "storage_dir": storage_dir,
                "files": {},
            }

        return {
            "ok": True,
            "context": context or {},
            "data": data,
            "source": "memory_actions_official",
            "started": False,
            "summary": f"memory_health ok={bool(data.get('ok', True))}",
            "timestamp": int(time.time()),
            "view": "memory_health",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "reason": str(e),
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_health",
        }


def action_memory_snapshot(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()
    fn = getattr(aicore, "memory_snapshot", None)
    if not callable(fn):
        return {
            "ok": False,
            "error": "memory_snapshot_not_available",
            "reason": "memory_snapshot_not_available",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_snapshot",
        }

    try:
        snap = fn() or {}
        keys = list(snap.keys()) if isinstance(snap, dict) else []
        return {
            "ok": True,
            "context": context or {},
            "snapshot": snap,
            "keys": keys,
            "source": "memory_actions_official",
            "started": False,
            "summary": f"memory_snapshot keys={len(keys)}",
            "timestamp": int(time.time()),
            "view": "memory_snapshot",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "reason": str(e),
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_snapshot",
        }


def action_memory_add(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()

    content = _ctx_value(context, kwargs, "content")
    memory_type = _ctx_value(context, kwargs, "memory_type", "fact")
    importance = float(_ctx_value(context, kwargs, "importance", 0.5))
    tags = _ctx_value(context, kwargs, "tags", None)
    metadata = _ctx_value(context, kwargs, "metadata", None)

    fn = getattr(aicore, "add_long_term_memory", None)
    if not callable(fn):
        return {
            "ok": False,
            "error": "add_long_term_memory_not_available",
            "reason": "add_long_term_memory_not_available",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_add",
        }

    try:
        result = fn(
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            metadata=metadata,
        )
        if result is None:
            return {
                "ok": False,
                "error": "memory_add_returned_none",
                "reason": "memory_add_returned_none",
                "source": "memory_actions_official",
                "timestamp": int(time.time()),
                "view": "memory_add",
            }

        return {
            "ok": True,
            "context": context or kwargs,
            "content_preview": _safe_json_preview(content),
            "memory_type": memory_type,
            "importance": importance,
            "tags": tags or [],
            "result": result,
            "source": "memory_actions_official",
            "started": False,
            "summary": f"memory_add ok type={memory_type} importance={importance}",
            "timestamp": int(time.time()),
            "used_method": "aicore.add_long_term_memory",
            "view": "memory_add",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "reason": str(e),
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_add",
        }


def action_memory_search(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()
    mm = getattr(aicore, "memory_manager", None)

    query = str(_ctx_value(context, kwargs, "query", "") or "").strip()
    limit = int(_ctx_value(context, kwargs, "limit", 5) or 5)

    if not query:
        return {
            "ok": False,
            "error": "empty_query",
            "reason": "empty_query",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_search",
        }

    results: List[Dict[str, Any]] = []
    used_method = "manual_snapshot_fallback"

    try:
        if mm is not None and hasattr(mm, "search_long_term_memories") and callable(mm.search_long_term_memories):
            raw = mm.search_long_term_memories(query=query, limit=limit) or []
            for item in raw:
                results.append({
                    "content": item,
                    "match_text": _safe_json_preview(getattr(item, "content", item), 500),
                })
            used_method = "memory_manager.search_long_term_memories"
        else:
            results = _manual_search_from_snapshot(aicore, query=query, limit=limit)
    except Exception:
        results = _manual_search_from_snapshot(aicore, query=query, limit=limit)

    return {
        "ok": True,
        "context": context or kwargs,
        "query": query,
        "limit": limit,
        "count": len(results),
        "results": results,
        "source": "memory_actions_official",
        "started": False,
        "summary": f"memory_search count={len(results)} query={query}",
        "timestamp": int(time.time()),
        "used_method": used_method,
        "view": "memory_search",
    }


def action_memory_recall(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    res = action_memory_search(context=context, **kwargs)
    res["view"] = "memory_recall"
    res["summary"] = f"memory_recall count={res.get('count', 0)} query={res.get('query', '')}"
    return res


def action_memory_append_chat(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()
    role = str(_ctx_value(context, kwargs, "role", "user") or "user")
    content = str(_ctx_value(context, kwargs, "content", "") or "")

    fn = getattr(aicore, "record_chat_memory", None)
    if not callable(fn):
        return {
            "ok": False,
            "error": "record_chat_memory_not_available",
            "reason": "record_chat_memory_not_available",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_append_chat",
        }

    try:
        _ensure_default_session(aicore)
        fn(role=role, content=content)
        return {
            "ok": True,
            "context": context or kwargs,
            "role": role,
            "content_preview": content[:200],
            "source": "memory_actions_official",
            "started": False,
            "summary": f"memory_append_chat ok role={role}",
            "timestamp": int(time.time()),
            "view": "memory_append_chat",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "reason": str(e),
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_append_chat",
        }


def action_memory_append_action(*, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    aicore = _resolve_aicore()
    action_name = str(_ctx_value(context, kwargs, "action_name", "") or "")
    status = str(_ctx_value(context, kwargs, "status", "success") or "success")
    result_summary = str(_ctx_value(context, kwargs, "result_summary", "") or "")

    fn = getattr(aicore, "record_action_memory", None)
    if not callable(fn):
        return {
            "ok": False,
            "error": "record_action_memory_not_available",
            "reason": "record_action_memory_not_available",
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_append_action",
        }

    try:
        _ensure_default_session(aicore)
        fn(action_name=action_name, status=status, result_summary=result_summary)
        return {
            "ok": True,
            "context": context or kwargs,
            "action_name": action_name,
            "status_text": status,
            "result_summary": result_summary,
            "source": "memory_actions_official",
            "started": False,
            "summary": f"memory_append_action ok action={action_name}",
            "timestamp": int(time.time()),
            "view": "memory_append_action",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "reason": str(e),
            "source": "memory_actions_official",
            "timestamp": int(time.time()),
            "view": "memory_append_action",
        }


def _action_exists(dispatcher: Any, name: str) -> bool:
    if dispatcher is None:
        return False
    getter = getattr(dispatcher, "get_action", None)
    if callable(getter):
        try:
            return getter(name) is not None
        except Exception:
            return False
    return False


def _register_one(dispatcher: Any, name: str, fn: Any) -> bool:
    if _action_exists(dispatcher, name):
        return False
    reg = getattr(dispatcher, "register_action", None)
    if not callable(reg):
        raise RuntimeError("dispatcher.register_action not available")
    reg(name, fn)
    return True


def register_actions(dispatcher: Any = None, aicore: Any = None) -> Dict[str, Any]:
    aicore = _resolve_aicore(aicore)
    dispatcher = _resolve_dispatcher(dispatcher, aicore)

    if dispatcher is None:
        return {
            "ok": False,
            "reason": "dispatcher_not_ready",
            "registered": [],
            "failed": ["dispatcher_not_ready"],
            "count_registered": 0,
            "count_failed": 1,
        }

    mapping = {
        "memory.health": action_memory_health,
        "memory.snapshot": action_memory_snapshot,
        "memory.search": action_memory_search,
        "memory.recall": action_memory_recall,
        "memory.add": action_memory_add,
        "memory.append_chat": action_memory_append_chat,
        "memory.append_action": action_memory_append_action,
    }

    registered: List[str] = []
    failed: List[str] = []

    for name, fn in mapping.items():
        try:
            _register_one(dispatcher, name, fn)
            registered.append(name)
        except Exception as e:
            if _action_exists(dispatcher, name):
                registered.append(name)
            else:
                failed.append(f"{name}: {e}")

    return {
        "ok": len(failed) == 0,
        "reason": "registered" if len(failed) == 0 else "partial_failed",
        "registered": registered,
        "failed": failed,
        "count_registered": len(registered),
        "count_failed": len(failed),
    }


def ensure_memory_actions_registered(dispatcher: Any = None, aicore: Any = None) -> Dict[str, Any]:
    return register_actions(dispatcher=dispatcher, aicore=aicore)


def main() -> int:
    root = _project_root_from_here()
    _ensure_sys_path(root)
    os.chdir(root)

    result = register_actions()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


__all__ = [
    "register_actions",
    "ensure_memory_actions_registered",
    "action_memory_health",
    "action_memory_snapshot",
    "action_memory_search",
    "action_memory_recall",
    "action_memory_add",
    "action_memory_append_chat",
    "action_memory_append_action",
]


if __name__ == "__main__":
    raise SystemExit(main())
