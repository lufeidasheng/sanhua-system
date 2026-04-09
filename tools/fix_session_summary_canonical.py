#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
import uuid
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
    s = str(s or "").strip()
    s = s.replace("\n", " ").replace("；", ";")
    s = " ".join(s.split())
    return s.lower()


def split_summary_clauses(summary: str) -> List[str]:
    raw = str(summary or "").replace("\n", " ")
    parts = [p.strip() for p in raw.split("；")]
    return [p for p in parts if p]


def dedupe_clauses(summary: str) -> str:
    seen = set()
    kept: List[str] = []
    for clause in split_summary_clauses(summary):
        key = norm_text(clause)
        if key in seen:
            continue
        seen.add(key)
        kept.append(clause)
    return "；".join(kept)


def normalize_summary_item(item: Any) -> Dict[str, Any] | None:
    if isinstance(item, dict):
        content = str(item.get("content") or item.get("summary") or "").strip()
        item_id = str(item.get("id") or uuid.uuid4())
        updated_at = str(item.get("updated_at") or item.get("timestamp") or now_iso())
    else:
        content = str(item or "").strip()
        item_id = str(uuid.uuid4())
        updated_at = now_iso()

    if not content:
        return None

    return {
        "id": item_id,
        "content": dedupe_clauses(content),
        "updated_at": updated_at,
    }


def choose_canonical_summary(
    active_context_summary: str,
    session_summaries: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], int]:
    candidates: List[Dict[str, Any]] = []

    if active_context_summary.strip():
        candidates.append({
            "id": str(uuid.uuid4()),
            "content": dedupe_clauses(active_context_summary),
            "updated_at": now_iso(),
        })

    candidates.extend(session_summaries)

    deduped_by_norm: Dict[str, Dict[str, Any]] = {}
    removed = 0

    for item in candidates:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        key = norm_text(content)
        if key in deduped_by_norm:
            removed += 1
            old = deduped_by_norm[key]
            # 保留内容更长、时间更新的
            if len(content) > len(str(old.get("content", ""))):
                old["content"] = content
            if str(item.get("updated_at", "")) > str(old.get("updated_at", "")):
                old["updated_at"] = item["updated_at"]
            continue
        deduped_by_norm[key] = dict(item)

    unique_items = list(deduped_by_norm.values())
    unique_items.sort(key=lambda x: (len(str(x.get("content", ""))), str(x.get("updated_at", ""))), reverse=True)

    if not unique_items:
        return "", [], removed

    canonical = unique_items[0]
    return canonical["content"], [canonical], removed


def main() -> None:
    parser = argparse.ArgumentParser(description="收敛 session summary 为唯一 canonical summary")
    parser.add_argument("--root", default=".", help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    memory_dir = root / "data" / "memory"
    session_cache_path = memory_dir / "session_cache.json"
    memory_index_path = memory_dir / "memory_index.json"

    bak1 = backup_file(session_cache_path)
    bak2 = backup_file(memory_index_path)

    session_cache = read_json(session_cache_path, {})
    memory_index = read_json(memory_index_path, {})

    active = session_cache.get("active_session", {})
    if not isinstance(active, dict):
        active = {}

    raw_context_summary = str(active.get("context_summary", "") or "").strip()
    raw_session_summaries = active.get("session_summaries", [])
    if not isinstance(raw_session_summaries, list):
        raw_session_summaries = []

    normalized_items: List[Dict[str, Any]] = []
    for item in raw_session_summaries:
        n = normalize_summary_item(item)
        if n:
            normalized_items.append(n)

    canonical_summary, canonical_items, removed = choose_canonical_summary(
        active_context_summary=raw_context_summary,
        session_summaries=normalized_items,
    )

    active["context_summary"] = canonical_summary
    active["session_summaries"] = canonical_items
    active["last_active_at"] = now_iso()

    session_cache["active_session"] = active
    session_cache["updated_at"] = now_iso()

    memory_index.setdefault("index", {})
    memory_index.setdefault("stats", {})
    memory_index["index"]["session_summary_ids"] = [item["id"] for item in canonical_items]
    memory_index["stats"]["session_summary_count"] = len(canonical_items)
    memory_index["updated_at"] = now_iso()

    write_json(session_cache_path, session_cache)
    write_json(memory_index_path, memory_index)

    print("=" * 72)
    print("session summary canonical 修复完成")
    print("=" * 72)
    print(f"root                   : {root}")
    print(f"session_cache_backup   : {bak1}")
    print(f"memory_index_backup    : {bak2}")
    print(f"raw_summary_count      : {len(raw_session_summaries)}")
    print(f"final_summary_count    : {len(canonical_items)}")
    print(f"removed_duplicates     : {removed}")
    print("-" * 72)
    print("canonical_context_summary:")
    print(canonical_summary)


if __name__ == "__main__":
    main()
