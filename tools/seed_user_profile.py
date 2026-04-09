#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List


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


def ensure_persona(persona: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(persona, dict):
        persona = {}

    persona.setdefault("version", "2.0")
    persona.setdefault("store", "sanhua_persona_memory")
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

    long_term.setdefault("version", "2.0")
    long_term.setdefault("store", "sanhua_long_term_memory")
    long_term["updated_at"] = now_iso()

    memories = long_term.get("memories", [])
    if not isinstance(memories, list):
        memories = []

    normalized: List[Dict[str, Any]] = []
    for item in memories:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "id": item.get("id") or str(uuid.uuid4()),
            "type": item.get("type", item.get("memory_type", "fact")),
            "key": item.get("key", ""),
            "value": item.get("value", item.get("content", "")),
            "content": item.get("content", ""),
            "confidence": float(item.get("confidence", item.get("importance", 0.8))),
            "source": item.get("source", "legacy_import"),
            "tags": item.get("tags", []),
            "updated_at": item.get("updated_at", now_iso()),
            "metadata": item.get("metadata", {}),
        })
    long_term["memories"] = normalized
    return long_term


def ensure_memory_index(memory_index: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(memory_index, dict):
        memory_index = {}

    memory_index.setdefault("version", "2.0")
    memory_index.setdefault("store", "sanhua_memory_index")
    memory_index["updated_at"] = now_iso()
    memory_index.setdefault("index", {})
    memory_index.setdefault("stats", {})
    return memory_index


def upsert_memory(memories: List[Dict[str, Any]], new_item: Dict[str, Any]) -> bool:
    sig = (new_item["type"], new_item["key"], json.dumps(new_item["value"], ensure_ascii=False, sort_keys=True))
    for i, item in enumerate(memories):
        old_sig = (item.get("type"), item.get("key"), json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True))
        if old_sig == sig:
            memories[i]["confidence"] = max(float(item.get("confidence", 0.0)), float(new_item.get("confidence", 0.0)))
            memories[i]["updated_at"] = now_iso()
            memories[i]["source"] = new_item.get("source", memories[i].get("source", "manual_seed"))
            tags = set(item.get("tags", [])) | set(new_item.get("tags", []))
            memories[i]["tags"] = sorted(tags)
            return False
    memories.append(new_item)
    return True


def rebuild_index(long_term: Dict[str, Any], persona: Dict[str, Any], memory_index: Dict[str, Any]) -> Dict[str, Any]:
    memories = long_term.get("memories", [])
    user_profile = persona.get("user_profile", {})

    long_term_ids = []
    memory_keys = []
    tags = set()

    for item in memories:
        if not isinstance(item, dict):
            continue
        if item.get("id"):
            long_term_ids.append(item["id"])
        if item.get("key"):
            memory_keys.append(item["key"])
        for tag in item.get("tags", []):
            tags.add(tag)

    memory_index["index"] = {
        "long_term_ids": long_term_ids,
        "memory_keys": sorted(set(memory_keys)),
        "persona_keys": sorted(user_profile.keys()),
        "tags": sorted(tags),
    }

    memory_index["stats"] = {
        "long_term_count": len(long_term_ids),
        "persona_field_count": len(user_profile.keys()),
        "user_name_present": bool(user_profile.get("name")),
        "preferred_style_count": len(user_profile.get("preferred_style", [])),
        "project_focus_count": len(user_profile.get("project_focus", [])),
    }

    memory_index["updated_at"] = now_iso()
    return memory_index


def main() -> None:
    root = Path(".").resolve()
    memory_dir = root / "data" / "memory"
    persona_path = memory_dir / "persona.json"
    long_term_path = memory_dir / "long_term.json"
    memory_index_path = memory_dir / "memory_index.json"

    backups = [
        backup_file(persona_path),
        backup_file(long_term_path),
        backup_file(memory_index_path),
    ]

    persona = ensure_persona(read_json(persona_path, {}))
    long_term = ensure_long_term(read_json(long_term_path, {}))
    memory_index = ensure_memory_index(read_json(memory_index_path, {}))

    # =========================
    # 1) 显式写入 user_profile
    # =========================
    user_profile = persona["user_profile"]

    user_profile["name"] = "鹏"
    user_profile["aliases"] = sorted(set(user_profile.get("aliases", []) + ["鹏", "鹏鹏"]))
    user_profile["preferred_style"] = sorted(set(user_profile.get("preferred_style", []) + [
        "务实",
        "系统化",
        "高信息密度",
        "结论优先",
        "避免空话",
        "偏好完整代码",
    ]))
    user_profile["response_preferences"] = {
        **user_profile.get("response_preferences", {}),
        "tone": "务实直接",
        "structure": "结论优先+执行建议+必要时给全量代码",
        "verbosity": "medium_high",
    }
    user_profile["project_focus"] = sorted(set(user_profile.get("project_focus", []) + [
        "三花聚顶",
        "AICore",
        "MemoryManager",
        "PromptMemoryBridge",
    ]))
    stable_facts = user_profile.get("stable_facts", {})
    stable_facts["identity.name"] = "鹏"
    stable_facts["system.primary_project"] = "三花聚顶"
    stable_facts["response.preference"] = "务实、系统化、高信息密度、结论优先"
    user_profile["stable_facts"] = stable_facts
    user_profile["notes"] = "用户为鹏；长期偏好务实、系统化、高信息密度、结论优先、避免空话。"
    user_profile["updated_at"] = now_iso()
    persona["user_profile"] = user_profile
    persona["updated_at"] = now_iso()

    # =========================
    # 2) 写入 long_term 结构化事实
    # =========================
    memories = long_term["memories"]

    seeded = 0
    seeded += int(upsert_memory(memories, {
        "id": str(uuid.uuid4()),
        "type": "identity",
        "key": "name",
        "value": "鹏",
        "content": "用户名字是鹏",
        "confidence": 0.99,
        "source": "manual_seed",
        "tags": ["user", "identity", "name"],
        "updated_at": now_iso(),
        "metadata": {},
    }))

    for style in ["务实", "系统化", "高信息密度", "结论优先", "避免空话", "偏好完整代码"]:
        seeded += int(upsert_memory(memories, {
            "id": str(uuid.uuid4()),
            "type": "preference",
            "key": "preferred_style",
            "value": style,
            "content": f"用户偏好回答风格：{style}",
            "confidence": 0.95,
            "source": "manual_seed",
            "tags": ["user", "preference", "style"],
            "updated_at": now_iso(),
            "metadata": {},
        }))

    for project in ["三花聚顶", "AICore"]:
        seeded += int(upsert_memory(memories, {
            "id": str(uuid.uuid4()),
            "type": "project_focus",
            "key": "project_focus",
            "value": project,
            "content": f"用户当前核心关注项目：{project}",
            "confidence": 0.95,
            "source": "manual_seed",
            "tags": ["project", "focus"],
            "updated_at": now_iso(),
            "metadata": {},
        }))

    seeded += int(upsert_memory(memories, {
        "id": str(uuid.uuid4()),
        "type": "architecture_fact",
        "key": "memory_architecture_focus",
        "value": "记忆层与其他 core 共存，并作为独立核心服务存在",
        "content": "用户当前关注记忆层与其他 core 共存的架构整理",
        "confidence": 0.95,
        "source": "manual_seed",
        "tags": ["memory", "architecture", "core"],
        "updated_at": now_iso(),
        "metadata": {},
    }))

    long_term["memories"] = memories
    long_term["updated_at"] = now_iso()

    # =========================
    # 3) 刷新 index
    # =========================
    memory_index = rebuild_index(long_term, persona, memory_index)

    write_json(persona_path, persona)
    write_json(long_term_path, long_term)
    write_json(memory_index_path, memory_index)

    print("=" * 72)
    print("用户画像种子写入完成")
    print("=" * 72)
    print(f"root                  : {root}")
    print(f"memory_dir            : {memory_dir}")
    print(f"backups               : {len([x for x in backups if x])}")
    print(f"new_or_upserted_facts : {seeded}")
    print("-" * 72)
    print(f"user_profile.name     : {persona['user_profile'].get('name', '')}")
    print(f"user_profile.aliases  : {persona['user_profile'].get('aliases', [])}")
    print(f"user_profile.styles   : {persona['user_profile'].get('preferred_style', [])}")
    print(f"user_profile.projects : {persona['user_profile'].get('project_focus', [])}")
    print("-" * 72)
    print("memory_index.stats:")
    print(json.dumps(memory_index.get("stats", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
