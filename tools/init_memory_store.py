#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶 Memory Store 初始化脚本

作用：
1. 创建 data/memory/ 目录
2. 初始化以下文件：
   - long_term.json
   - persona.json
   - session_cache.json
   - memory_index.json
3. 若文件已存在：
   - 默认不覆盖
   - 可用 --force 强制重建
4. 若旧文件存在（如 memory.json / memory_data.json），可用 --seed-from-old 尝试导入部分信息

用法示例：
    python3 tools/init_memory_store.py
    python3 tools/init_memory_store.py --root "/Users/lufei/Desktop/聚核助手2.0"
    python3 tools/init_memory_store.py --force
    python3 tools/init_memory_store.py --seed-from-old
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json_if_exists(path: Path) -> Optional[Any]:
    if not path.exists() or not path.is_file():
        return None
    encodings = ("utf-8", "utf-8-sig", "gbk", "latin-1")
    for enc in encodings:
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup)
    return backup


def default_long_term() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "store": "sanhua_long_term_memory",
        "updated_at": now_iso(),
        "memories": []
    }


def default_persona() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "store": "sanhua_persona_memory",
        "updated_at": now_iso(),
        "persona": {
            "name": "三花聚顶",
            "system_identity": "",
            "style": "",
            "goals": [],
            "constraints": [],
            "preferences": {},
            "traits": [],
            "notes": ""
        }
    }


def default_session_cache() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "store": "sanhua_session_cache",
        "updated_at": now_iso(),
        "active_session": {
            "session_id": "",
            "started_at": "",
            "last_active_at": "",
            "context_summary": "",
            "recent_messages": [],
            "recent_actions": [],
            "ephemeral_memory": []
        },
        "recent_sessions": []
    }


def default_memory_index() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "store": "sanhua_memory_index",
        "updated_at": now_iso(),
        "index": {
            "long_term_ids": [],
            "persona_keys": [
                "name",
                "system_identity",
                "style",
                "goals",
                "constraints",
                "preferences",
                "traits",
                "notes"
            ],
            "session_ids": []
        },
        "stats": {
            "long_term_count": 0,
            "persona_field_count": 8,
            "recent_session_count": 0
        }
    }


def try_seed_from_old(root: Path) -> Dict[str, Any]:
    """
    从旧文件中尽量提取一点信息，不做激进迁移。
    只做保守吸收。
    """
    seed_result = {
        "long_term": default_long_term(),
        "persona": default_persona(),
        "session_cache": default_session_cache(),
        "memory_index": default_memory_index(),
        "notes": []
    }

    old_candidates = [
        root / "memory.json",
        root / "memory_data.json",
        root / "data" / "memory_data.json",
        root / "core" / "aicore" / "memory_data.json",
        root / "core" / "aicore" / "memory" / "memory.json",
        root / "core" / "aicore" / "memory" / "memory_data.json",
    ]

    found_any = False

    for old_path in old_candidates:
        data = read_json_if_exists(old_path)
        if data is None:
            continue

        found_any = True
        seed_result["notes"].append(f"读取旧文件: {old_path.as_posix()}")

        # 1) 如果旧数据本身就是 list，直接尝试作为长期记忆列表吸收
        if isinstance(data, list):
            for i, item in enumerate(data, start=1):
                seed_result["long_term"]["memories"].append({
                    "id": f"legacy_{i}",
                    "type": "legacy_import",
                    "source": old_path.as_posix(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "importance": 0.5,
                    "tags": ["legacy"],
                    "content": item,
                    "metadata": {}
                })

        # 2) 如果旧数据是 dict，尽可能做保守映射
        elif isinstance(data, dict):
            # 常见人格字段尝试吸收
            persona = seed_result["persona"]["persona"]
            for key in ["name", "style", "notes", "system_identity"]:
                if key in data and not persona.get(key):
                    persona[key] = data.get(key) or persona.get(key, "")

            # 常见列表字段
            for key in ["goals", "constraints", "traits"]:
                if key in data and isinstance(data[key], list) and not persona.get(key):
                    persona[key] = data[key]

            # 常见 preferences
            if "preferences" in data and isinstance(data["preferences"], dict):
                persona["preferences"].update(data["preferences"])

            # 若发现 memories 字段
            if "memories" in data and isinstance(data["memories"], list):
                for i, item in enumerate(data["memories"], start=1):
                    seed_result["long_term"]["memories"].append({
                        "id": f"legacy_memories_{i}",
                        "type": "legacy_import",
                        "source": old_path.as_posix(),
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                        "importance": 0.5,
                        "tags": ["legacy"],
                        "content": item,
                        "metadata": {}
                    })

            # 若发现 log / records / history 等字段，粗略吸收
            for bucket_key in ["records", "history", "items", "data"]:
                if bucket_key in data and isinstance(data[bucket_key], list):
                    for i, item in enumerate(data[bucket_key], start=1):
                        seed_result["long_term"]["memories"].append({
                            "id": f"{bucket_key}_{i}",
                            "type": "legacy_import",
                            "source": old_path.as_posix(),
                            "created_at": now_iso(),
                            "updated_at": now_iso(),
                            "importance": 0.4,
                            "tags": ["legacy", bucket_key],
                            "content": item,
                            "metadata": {}
                        })

    # 更新 index / stats
    long_term_ids = []
    for item in seed_result["long_term"]["memories"]:
        mid = item.get("id")
        if mid:
            long_term_ids.append(mid)

    seed_result["memory_index"]["index"]["long_term_ids"] = long_term_ids
    seed_result["memory_index"]["stats"]["long_term_count"] = len(long_term_ids)
    seed_result["memory_index"]["stats"]["recent_session_count"] = len(
        seed_result["session_cache"].get("recent_sessions", [])
    )

    # 更新时间
    for key in ["long_term", "persona", "session_cache", "memory_index"]:
        seed_result[key]["updated_at"] = now_iso()

    if not found_any:
        seed_result["notes"].append("未发现可导入的旧 memory 文件，使用默认模板初始化。")

    return seed_result


def init_one_file(path: Path, data: Dict[str, Any], force: bool) -> str:
    if path.exists():
        if not force:
            return f"SKIP   已存在，未覆盖: {path.as_posix()}"
        backup = backup_file(path)
        write_json(path, data)
        if backup:
            return f"RESET  已重建并备份: {path.as_posix()} -> {backup.name}"
        return f"RESET  已重建: {path.as_posix()}"

    write_json(path, data)
    return f"CREATE 已创建: {path.as_posix()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化三花聚顶 memory store")
    parser.add_argument(
        "--root",
        default=".",
        help="项目根目录，默认当前目录"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="若目标文件已存在，则备份后重建"
    )
    parser.add_argument(
        "--seed-from-old",
        action="store_true",
        help="尝试从旧 memory 文件中吸收部分信息"
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"[ERROR] 根目录不存在: {root}")
        return 2

    memory_dir = root / "data" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    if args.seed_from_old:
        seeded = try_seed_from_old(root)
        long_term_data = seeded["long_term"]
        persona_data = seeded["persona"]
        session_cache_data = seeded["session_cache"]
        memory_index_data = seeded["memory_index"]
        seed_notes = seeded["notes"]
    else:
        long_term_data = default_long_term()
        persona_data = default_persona()
        session_cache_data = default_session_cache()
        memory_index_data = default_memory_index()
        seed_notes = ["未启用 --seed-from-old，使用默认模板初始化。"]

    actions = []
    actions.append(init_one_file(memory_dir / "long_term.json", long_term_data, args.force))
    actions.append(init_one_file(memory_dir / "persona.json", persona_data, args.force))
    actions.append(init_one_file(memory_dir / "session_cache.json", session_cache_data, args.force))
    actions.append(init_one_file(memory_dir / "memory_index.json", memory_index_data, args.force))

    print("=" * 72)
    print("三花聚顶 Memory Store 初始化完成")
    print("=" * 72)
    print(f"项目根目录 : {root.as_posix()}")
    print(f"Memory目录 : {memory_dir.as_posix()}")
    print("-" * 72)
    for line in actions:
        print(line)
    print("-" * 72)
    print("说明：")
    for note in seed_notes:
        print(f"- {note}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
