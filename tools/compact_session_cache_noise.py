#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple


TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def norm_text(s: str) -> str:
    s = str(s or "").strip().replace("\n", " ")
    return " ".join(s.split()).lower()


def compact_recent_messages(messages: List[Dict[str, Any]], keep_max: int = 12) -> Tuple[List[Dict[str, Any]], int]:
    """
    规则：
    1. 按 role + content 归一化去重，只保留最新一条
    2. 最终只保留最新 keep_max 条
    """
    if not isinstance(messages, list):
        return [], 0

    latest_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        content = str(msg.get("content", "")).strip()
        if not role or not content:
            continue

        key = (role, norm_text(content))
        old = latest_by_key.get(key)
        if old is None:
            latest_by_key[key] = msg
            continue

        old_ts = str(old.get("timestamp", ""))
        new_ts = str(msg.get("timestamp", ""))
        if new_ts >= old_ts:
            latest_by_key[key] = msg

    kept = list(latest_by_key.values())
    kept.sort(key=lambda x: str(x.get("timestamp", "")))
    removed = max(0, len(messages) - len(kept))

    if len(kept) > keep_max:
        removed += len(kept) - keep_max
        kept = kept[-keep_max:]

    return kept, removed


def compact_recent_actions(actions: List[Dict[str, Any]], keep_max: int = 16) -> Tuple[List[Dict[str, Any]], int]:
    """
    规则：
    1. 对 memory.consolidate / aicore.shutdown 这类低价值动作，只保留最新 1 条
    2. degraded / failed 的动作优先保留
    3. 最终只保留最新 keep_max 条
    """
    if not isinstance(actions, list):
        return [], 0

    noisy_singletons = {
        "memory.consolidate",
        "aicore.shutdown",
    }

    newest_noisy: Dict[str, Dict[str, Any]] = {}
    valuable: List[Dict[str, Any]] = []

    for act in actions:
        if not isinstance(act, dict):
            continue
        name = str(act.get("action_name", "")).strip()
        status = str(act.get("status", "")).strip().lower()
        ts = str(act.get("timestamp", ""))

        if name in noisy_singletons:
            old = newest_noisy.get(name)
            if old is None or ts >= str(old.get("timestamp", "")):
                newest_noisy[name] = act
        else:
            valuable.append(act)

    kept = valuable + list(newest_noisy.values())
    kept.sort(key=lambda x: str(x.get("timestamp", "")))

    removed = max(0, len(actions) - len(kept))

    if len(kept) > keep_max:
        # 优先保留 degraded / failed
        important = [x for x in kept if str(x.get("status", "")).lower() in {"degraded", "failed", "error"}]
        normal = [x for x in kept if x not in important]
        important.sort(key=lambda x: str(x.get("timestamp", "")))
        normal.sort(key=lambda x: str(x.get("timestamp", "")))

        merged = important + normal
        kept = merged[-keep_max:]
        kept.sort(key=lambda x: str(x.get("timestamp", "")))
        removed = max(0, len(actions) - len(kept))

    return kept, removed


def main() -> None:
    parser = argparse.ArgumentParser(description="压缩 session_cache 噪音")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--keep-messages", type=int, default=12)
    parser.add_argument("--keep-actions", type=int, default=16)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    memory_dir = root / "data" / "memory"
    session_cache_path = memory_dir / "session_cache.json"

    bak = backup_file(session_cache_path)

    session_cache = read_json(session_cache_path, {})
    active = session_cache.get("active_session", {})
    if not isinstance(active, dict):
        active = {}

    old_messages = active.get("recent_messages", [])
    old_actions = active.get("recent_actions", [])

    new_messages, removed_messages = compact_recent_messages(old_messages, keep_max=args.keep_messages)
    new_actions, removed_actions = compact_recent_actions(old_actions, keep_max=args.keep_actions)

    active["recent_messages"] = new_messages
    active["recent_actions"] = new_actions
    active["last_active_at"] = now_iso()

    session_cache["version"] = "2.0"
    session_cache["updated_at"] = now_iso()
    session_cache["active_session"] = active

    write_json(session_cache_path, session_cache)

    print("=" * 72)
    print("session_cache 噪音压缩完成")
    print("=" * 72)
    print(f"root                 : {root}")
    print(f"backup               : {bak}")
    print(f"messages_before      : {len(old_messages) if isinstance(old_messages, list) else 0}")
    print(f"messages_after       : {len(new_messages)}")
    print(f"messages_removed     : {removed_messages}")
    print(f"actions_before       : {len(old_actions) if isinstance(old_actions, list) else 0}")
    print(f"actions_after        : {len(new_actions)}")
    print(f"actions_removed      : {removed_actions}")
    print("-" * 72)
    print("kept_message_previews:")
    for i, msg in enumerate(new_messages[-5:], 1):
        print(f"[{i}] {msg.get('role')} | {str(msg.get('content', ''))[:80]}")
    print("-" * 72)
    print("kept_action_previews:")
    for i, act in enumerate(new_actions[-8:], 1):
        print(f"[{i}] {act.get('action_name')} | {act.get('status')} | {str(act.get('result_summary', ''))[:80]}")


if __name__ == "__main__":
    main()
