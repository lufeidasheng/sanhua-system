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


def normalize_text(value: Any) -> str:
    s = str(value or "").strip()
    s = s.replace("。", "").replace(".", "").replace("，", ",").replace("；", ";")
    s = " ".join(s.split())
    return s.lower()


def ensure_persona(persona: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(persona, dict):
        persona = {}

    persona["version"] = "2.0"
    persona["store"] = persona.get("store") or "sanhua_persona_memory"
    persona["updated_at"] = now_iso()

    system_persona = persona.get("system_persona", {})
    if not isinstance(system_persona, dict):
        system_persona = {}

    system_persona.setdefault("name", "三花聚顶")
    system_persona.setdefault("system_identity", "")
    system_persona.setdefault("style", "务实、模块化、系统化")
    system_persona.setdefault("goals", [])
    system_persona.setdefault("constraints", [])
    system_persona.setdefault("preferences", {})
    system_persona.setdefault("traits", [])
    system_persona.setdefault("notes", "")

    user_profile = persona.get("user_profile", {})
    if not isinstance(user_profile, dict):
        user_profile = {}

    user_profile.setdefault("name", "")
    user_profile.setdefault("aliases", [])
    user_profile.setdefault("preferred_style", [])
    user_profile.setdefault("response_preferences", {})
    user_profile.setdefault("project_focus", [])
    user_profile.setdefault("stable_facts", {})
    user_profile.setdefault("notes", "")
    user_profile["updated_at"] = now_iso()

    persona["system_persona"] = system_persona
    persona["user_profile"] = user_profile
    return persona


def ensure_long_term(long_term: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(long_term, dict):
        long_term = {}

    long_term["version"] = "2.0"
    long_term["store"] = long_term.get("store") or "sanhua_long_term_memory"
    long_term["updated_at"] = now_iso()

    memories = long_term.get("memories", [])
    if not isinstance(memories, list):
        memories = []

    normalized: List[Dict[str, Any]] = []
    for item in memories:
        if not isinstance(item, dict):
            continue

        normalized.append({
            "id": str(item.get("id") or uuid.uuid4()),
            "type": str(item.get("type", item.get("memory_type", "fact"))).strip() or "fact",
            "key": str(item.get("key", "")).strip(),
            "value": item.get("value", item.get("content", "")),
            "content": str(item.get("content", "")).strip(),
            "confidence": float(item.get("confidence", item.get("importance", 0.8)) or 0.8),
            "source": str(item.get("source", "memory_manager")).strip() or "memory_manager",
            "tags": item.get("tags", []) if isinstance(item.get("tags", []), list) else [],
            "updated_at": str(item.get("updated_at", item.get("timestamp", now_iso()))).strip() or now_iso(),
            "metadata": item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {},
        })

    long_term["memories"] = normalized
    return long_term


def ensure_memory_index(memory_index: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(memory_index, dict):
        memory_index = {}

    memory_index["version"] = "2.0"
    memory_index["store"] = memory_index.get("store") or "sanhua_memory_index"
    memory_index["updated_at"] = now_iso()
    memory_index.setdefault("index", {})
    memory_index.setdefault("stats", {})
    return memory_index


def canonicalize_architecture_fact(item: Dict[str, Any]) -> Dict[str, Any]:
    value_norm = normalize_text(item.get("value", ""))
    content_norm = normalize_text(item.get("content", ""))

    targets = {
        normalize_text("记忆层应与其他 core 共存，并作为独立核心服务存在。"),
        normalize_text("记忆层与其他 core 共存，并作为独立核心服务存在"),
    }

    if item.get("type") == "architecture_fact" and (value_norm in targets or content_norm in targets):
        item["key"] = "memory_architecture_focus"
        item["value"] = "记忆层与其他 core 共存，并作为独立核心服务存在"
        if not item.get("content"):
            item["content"] = "用户当前关注记忆层与其他 core 共存的架构整理"
    return item


def dedupe_memories(memories: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    merged: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    removed = 0

    for raw in memories:
        item = canonicalize_architecture_fact(dict(raw))

        type_ = str(item.get("type", "")).strip()
        key = str(item.get("key", "")).strip()
        value_norm = normalize_text(item.get("value", ""))
        content_norm = normalize_text(item.get("content", ""))

        # key 为空时，尽量用 type + value 落地
        if type_ == "architecture_fact" and not key and value_norm == normalize_text("记忆层与其他 core 共存，并作为独立核心服务存在"):
            key = "memory_architecture_focus"
            item["key"] = key

        signature = (type_, key, value_norm, content_norm)

        if signature not in merged:
            merged[signature] = item
            continue

        old = merged[signature]
        removed += 1

        old["confidence"] = max(float(old.get("confidence", 0.0)), float(item.get("confidence", 0.0)))
        old["tags"] = sorted(set(old.get("tags", [])) | set(item.get("tags", [])))
        old["updated_at"] = max(str(old.get("updated_at", "")), str(item.get("updated_at", "")))
        if len(str(item.get("content", ""))) > len(str(old.get("content", ""))):
            old["content"] = item.get("content", old.get("content", ""))
        if not old.get("key") and item.get("key"):
            old["key"] = item["key"]
        if not old.get("value") and item.get("value"):
            old["value"] = item["value"]

    deduped = list(merged.values())

    # 排序：identity / preference / project_focus / architecture_fact 优先
    priority = {
        "identity": 0,
        "preference": 1,
        "project_focus": 2,
        "architecture_fact": 3,
    }

    deduped.sort(
        key=lambda x: (
            priority.get(str(x.get("type", "")), 99),
            str(x.get("key", "")),
            str(x.get("updated_at", "")),
        )
    )

    return deduped, removed


def rebuild_index(
    long_term: Dict[str, Any],
    persona: Dict[str, Any],
    session_cache: Dict[str, Any],
    memory_index: Dict[str, Any],
) -> Dict[str, Any]:
    memories = long_term.get("memories", []) if isinstance(long_term.get("memories", []), list) else []
    user_profile = persona.get("user_profile", {}) if isinstance(persona.get("user_profile", {}), dict) else {}
    active_session = session_cache.get("active_session", {}) if isinstance(session_cache.get("active_session", {}), dict) else {}

    long_term_ids: List[str] = []
    memory_keys: List[str] = []
    tags = set()

    for item in memories:
        if not isinstance(item, dict):
            continue
        mem_id = str(item.get("id", "")).strip()
        if mem_id:
            long_term_ids.append(mem_id)
        mem_key = str(item.get("key", "")).strip()
        if mem_key:
            memory_keys.append(mem_key)
        for tag in item.get("tags", []):
            tags.add(str(tag))

    session_summary_ids: List[str] = []
    raw_summaries = active_session.get("session_summaries", [])
    if isinstance(raw_summaries, list):
        for s in raw_summaries:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "")).strip()
            if sid:
                session_summary_ids.append(sid)

    memory_index["index"] = {
        "long_term_ids": long_term_ids,
        "memory_keys": sorted(set(memory_keys)),
        "session_summary_ids": session_summary_ids,
        "persona_keys": sorted(user_profile.keys()),
        "tags": sorted(tags),
    }

    memory_index["stats"] = {
        "long_term_count": len(long_term_ids),
        "session_summary_count": len(session_summary_ids),
        "persona_field_count": len(user_profile.keys()),
        "user_name_present": bool(user_profile.get("name")),
        "preferred_style_count": len(user_profile.get("preferred_style", [])) if isinstance(user_profile.get("preferred_style", []), list) else 0,
        "project_focus_count": len(user_profile.get("project_focus", [])) if isinstance(user_profile.get("project_focus", []), list) else 0,
    }

    memory_index["updated_at"] = now_iso()
    return memory_index


def main() -> None:
    parser = argparse.ArgumentParser(description="统一 memory version 到 2.0，并做长期记忆去重")
    parser.add_argument("--root", default=".", help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    memory_dir = root / "data" / "memory"

    persona_path = memory_dir / "persona.json"
    long_term_path = memory_dir / "long_term.json"
    memory_index_path = memory_dir / "memory_index.json"
    session_cache_path = memory_dir / "session_cache.json"

    backups = [
        backup_file(persona_path),
        backup_file(long_term_path),
        backup_file(memory_index_path),
    ]

    persona = ensure_persona(read_json(persona_path, {}))
    long_term = ensure_long_term(read_json(long_term_path, {}))
    memory_index = ensure_memory_index(read_json(memory_index_path, {}))
    session_cache = read_json(session_cache_path, {})

    before_count = len(long_term.get("memories", []))
    deduped, removed_count = dedupe_memories(long_term.get("memories", []))
    long_term["memories"] = deduped
    long_term["updated_at"] = now_iso()

    # 补一手 user_profile.stable_facts
    user_profile = persona.get("user_profile", {})
    if isinstance(user_profile, dict):
        stable_facts = user_profile.get("stable_facts", {})
        if not isinstance(stable_facts, dict):
            stable_facts = {}

        if str(user_profile.get("name", "")).strip():
            stable_facts["identity.name"] = str(user_profile.get("name", "")).strip()

        has_arch = any(
            isinstance(m, dict)
            and m.get("type") == "architecture_fact"
            and str(m.get("key", "")).strip() == "memory_architecture_focus"
            for m in deduped
        )
        if has_arch:
            stable_facts["memory_architecture_focus"] = "记忆层与其他 core 共存，并作为独立核心服务存在"

        user_profile["stable_facts"] = stable_facts
        user_profile["updated_at"] = now_iso()
        persona["user_profile"] = user_profile
        persona["updated_at"] = now_iso()

    memory_index = rebuild_index(long_term, persona, session_cache, memory_index)

    write_json(persona_path, persona)
    write_json(long_term_path, long_term)
    write_json(memory_index_path, memory_index)

    print("=" * 72)
    print("memory 版本统一与去重完成")
    print("=" * 72)
    print(f"root                 : {root}")
    print(f"memory_dir           : {memory_dir}")
    print(f"backups              : {len([x for x in backups if x])}")
    print(f"long_term_before     : {before_count}")
    print(f"long_term_after      : {len(deduped)}")
    print(f"removed_duplicates   : {removed_count}")
    print("-" * 72)
    print(f"persona.version      : {persona.get('version')}")
    print(f"long_term.version    : {long_term.get('version')}")
    print(f"memory_index.version : {memory_index.get('version')}")
    print("-" * 72)
    print("index_stats:")
    print(json.dumps(memory_index.get("stats", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
