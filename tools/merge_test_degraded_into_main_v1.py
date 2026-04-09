#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

TZ8 = timezone(timedelta(hours=8))
MAIN_SUMMARY = "模型给出了不完整或不可信的最终答案"


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


def stable_id(action_name: str, status: str, result_summary: str, last_ts: str) -> str:
    raw = f"{action_name}|{status}|{result_summary}|{last_ts}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def is_degraded_chat(a: Dict[str, Any]) -> bool:
    return (
        str(a.get("action_name", "")).strip() == "aicore.chat"
        and str(a.get("status", "")).strip() == "degraded"
    )


def is_main_degraded(a: Dict[str, Any]) -> bool:
    return is_degraded_chat(a) and str(a.get("result_summary", "")).strip() == MAIN_SUMMARY


def is_test_degraded(a: Dict[str, Any]) -> bool:
    if not is_degraded_chat(a):
        return False
    s = str(a.get("result_summary", "")).strip().lower()
    return s.startswith("test degraded #")


def parse_occurrence_count(a: Dict[str, Any]) -> int:
    meta = a.get("metadata", {})
    if not isinstance(meta, dict):
        return 1
    v = meta.get("occurrence_count", 1)
    try:
        return max(1, int(v))
    except Exception:
        return 1


def collect_original_ids(a: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    meta = a.get("metadata", {})
    if isinstance(meta, dict):
        got = meta.get("original_ids", [])
        if isinstance(got, list):
            ids.extend([str(x).strip() for x in got if str(x).strip()])
    aid = str(a.get("id", "")).strip()
    if aid and aid not in ids:
        ids.append(aid)
    return ids


def merge_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(actions, list):
        return []

    main_idx: Optional[int] = None
    test_indices: List[int] = []

    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            continue
        if is_main_degraded(a) and main_idx is None:
            main_idx = i
        elif is_test_degraded(a):
            test_indices.append(i)

    if not test_indices:
        return actions

    test_items = [actions[i] for i in test_indices]
    test_total = len(test_items)
    test_original_ids: List[str] = []
    test_timestamps: List[str] = []

    for t in test_items:
        test_original_ids.extend(collect_original_ids(t))
        ts = str(t.get("timestamp", "")).strip()
        if ts:
            test_timestamps.append(ts)

    if main_idx is not None:
        main = dict(actions[main_idx])
        meta = dict(main.get("metadata", {}) or {})

        old_count = parse_occurrence_count(main)
        new_count = old_count + test_total

        orig_ids = collect_original_ids(main)
        for x in test_original_ids:
            if x not in orig_ids:
                orig_ids.append(x)

        first_ts = str(meta.get("first_timestamp", main.get("timestamp", ""))).strip()
        last_ts = str(meta.get("last_timestamp", main.get("timestamp", ""))).strip()
        if test_timestamps:
            sorted_ts = sorted([x for x in [first_ts, last_ts, *test_timestamps] if x])
            if sorted_ts:
                first_ts = sorted_ts[0]
                last_ts = sorted_ts[-1]

        meta["compacted"] = True
        meta["occurrence_count"] = new_count
        meta["first_timestamp"] = first_ts or now_iso()
        meta["last_timestamp"] = last_ts or now_iso()
        meta["original_ids"] = orig_ids
        meta["merged_test_degraded_count"] = meta.get("merged_test_degraded_count", 0) + test_total

        main["metadata"] = meta
        main["timestamp"] = last_ts or str(main.get("timestamp", "")).strip() or now_iso()
        main["id"] = stable_id(
            str(main.get("action_name", "")).strip(),
            str(main.get("status", "")).strip(),
            str(main.get("result_summary", "")).strip(),
            main["timestamp"],
        )
        actions[main_idx] = main
    else:
        all_ts = sorted([x for x in test_timestamps if x])
        first_ts = all_ts[0] if all_ts else now_iso()
        last_ts = all_ts[-1] if all_ts else now_iso()
        merged = {
            "id": stable_id("aicore.chat", "degraded", MAIN_SUMMARY, last_ts),
            "action_name": "aicore.chat",
            "status": "degraded",
            "result_summary": MAIN_SUMMARY,
            "metadata": {
                "compacted": True,
                "occurrence_count": test_total,
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
                "original_ids": test_original_ids,
                "merged_test_degraded_count": test_total,
                "synthetic_from_tests": True,
            },
            "timestamp": last_ts,
        }
        insert_at = min(test_indices)
        actions.insert(insert_at, merged)
        # 修正 test_indices，因为插入后索引右移
        test_indices = [i + 1 for i in test_indices]

    remove_set = set(test_indices)
    result = [a for i, a in enumerate(actions) if i not in remove_set]
    return result


def preview(actions: List[Dict[str, Any]], limit: int = 12) -> List[str]:
    out: List[str] = []
    for i, a in enumerate(actions[:limit], 1):
        meta = a.get("metadata", {}) if isinstance(a, dict) else {}
        count = meta.get("occurrence_count") if isinstance(meta, dict) else None
        extra = f" | x{count}" if count and str(count) != "1" else ""
        out.append(
            f"[{i}] {a.get('action_name', '')} | {a.get('status', '')} | {a.get('result_summary', '')}{extra}"
        )
    return out


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
    before = active.get("recent_actions", [])
    before_count = len(before) if isinstance(before, list) else 0

    after = merge_actions(list(before) if isinstance(before, list) else [])
    active["recent_actions"] = after
    active["last_active_at"] = now_iso()
    data["updated_at"] = now_iso()

    save_json(session_cache, data)

    print("=" * 72)
    print("test degraded 并入主 degraded 完成")
    print("=" * 72)
    print(f"root            : {root}")
    print(f"backup          : {bak}")
    print(f"actions_before  : {before_count}")
    print(f"actions_after   : {len(after)}")
    print(f"actions_removed : {before_count - len(after)}")
    print("-" * 72)
    print("after_action_previews:")
    for line in preview(after):
        print(line)


if __name__ == "__main__":
    main()
