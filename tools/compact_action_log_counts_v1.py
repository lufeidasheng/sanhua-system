#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

TZ8 = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ8).isoformat()


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_group_id(action_name: str, status: str, result_summary: str, first_ts: str, last_ts: str) -> str:
    raw = f"{action_name}|{status}|{result_summary}|{first_ts}|{last_ts}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def group_key(a: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(a.get("action_name", "")).strip(),
        str(a.get("status", "")).strip(),
        str(a.get("result_summary", "")).strip(),
    )


def should_compact(a: Dict[str, Any]) -> bool:
    return (
        str(a.get("action_name", "")).strip() == "aicore.chat"
        and str(a.get("status", "")).strip() == "degraded"
    )


def compact_actions(actions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    if not isinstance(actions, list):
        return [], 0

    compacted: List[Dict[str, Any]] = []
    removed = 0

    i = 0
    n = len(actions)

    while i < n:
        cur = actions[i]
        if not isinstance(cur, dict):
            i += 1
            continue

        if not should_compact(cur):
            compacted.append(cur)
            i += 1
            continue

        k = group_key(cur)
        group = [cur]
        j = i + 1

        while j < n:
            nxt = actions[j]
            if not isinstance(nxt, dict):
                break
            if group_key(nxt) != k:
                break
            if not should_compact(nxt):
                break
            group.append(nxt)
            j += 1

        if len(group) == 1:
            compacted.append(cur)
        else:
            first = group[0]
            last = group[-1]
            original_ids = [str(x.get("id", "")).strip() for x in group if str(x.get("id", "")).strip()]
            first_ts = str(first.get("timestamp", "")).strip()
            last_ts = str(last.get("timestamp", "")).strip()
            action_name, status, result_summary = k

            merged = {
                "id": stable_group_id(action_name, status, result_summary, first_ts, last_ts),
                "action_name": action_name,
                "status": status,
                "result_summary": result_summary,
                "metadata": {
                    "compacted": True,
                    "occurrence_count": len(group),
                    "first_timestamp": first_ts,
                    "last_timestamp": last_ts,
                    "original_ids": original_ids,
                },
                "timestamp": last_ts or now_iso(),
            }
            compacted.append(merged)
            removed += len(group) - 1

        i = j

    return compacted, removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    session_cache = root / "data" / "memory" / "session_cache.json"
    if not session_cache.exists():
        raise SystemExit(f"未找到: {session_cache}")

    bak = backup(session_cache)
    data = load_json(session_cache)

    active = data.setdefault("active_session", {})
    before_actions = active.get("recent_actions", [])
    before_count = len(before_actions) if isinstance(before_actions, list) else 0

    after_actions, removed = compact_actions(before_actions if isinstance(before_actions, list) else [])
    active["recent_actions"] = after_actions
    active["last_active_at"] = now_iso()
    data["updated_at"] = now_iso()

    save_json(session_cache, data)

    print("=" * 72)
    print("action log counts 压缩完成")
    print("=" * 72)
    print(f"root            : {root}")
    print(f"backup          : {bak}")
    print(f"actions_before  : {before_count}")
    print(f"actions_after   : {len(after_actions)}")
    print(f"actions_removed : {removed}")
    print("-" * 72)
    print("after_action_previews:")
    for idx, a in enumerate(after_actions[:12], 1):
        meta = a.get("metadata", {}) if isinstance(a, dict) else {}
        count = meta.get("occurrence_count")
        suffix = f" | x{count}" if count and int(count) > 1 else ""
        print(
            f"[{idx}] "
            f"{a.get('action_name', '')} | "
            f"{a.get('status', '')} | "
            f"{a.get('result_summary', '')}{suffix}"
        )


if __name__ == "__main__":
    main()
