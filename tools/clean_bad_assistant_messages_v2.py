#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


TARGET = Path("data/memory/session_cache.json")

BAD_SNIPPETS = [
    "三花聚顶记忆层接入AICore",
    "_process_request",
    "get_context(",
    "get_relevant_memories(",
    "_save_long_term_memory",
    "_load_long_term",
    "load_long_term_memory",
    "user_identity",
    "memory_type='long_term'",
    "threshold=0.75",
    "long_term_shard_",
    "msgpack",
    "LRU缓存",
    "分片存储",
    "序列化格式升级",
    "build_contextual_prompt",
    "_build_enhanced_prompt",
    "_call_model(",
    "PromptMemoryBridge(session_id=",
    "双向数据通道",
    "扩展模块",
    "增量压缩",
    "检索优化",
    "持久化绑定",
    "长期记忆关联",
    "字段级压缩",
    "分块压缩策略",
    "下游消费者",
    "会话级记忆隔离",
    "get_memory()",
    "set_memory()",
    "save_to_long_term()",
    "compress_memory()",
    "decompress_data()",
    "load_long_term()",
    "update_identity()",
]

BAD_REGEXES = [
    r"def\s+_process_request\s*\(",
    r"def\s+get_context\s*\(",
    r"def\s+_save_long_term_memory\s*\(",
    r"def\s+_load_long_term\s*\(",
    r"def\s+generate_response\s*\(",
    r"def\s+load_user_memory\s*\(",
    r"def\s+validate_answer\s*\(",
    r"def\s+load_user_identity\s*\(",
    r"def\s+validate_user\s*\(",
    r"def\s+compress_memory\s*\(",
    r"def\s+decompress_data\s*\(",
    r"def\s+update_identity\s*\(",
    r"MemoryManager\(\)\.get_relevant_memories\s*\(",
    r"memory_bridge\.sync_memory\s*\(",
    r"memory_bridge\.check_memory_completeness\s*\(",
    r"bridge\.get_memory\s*\(",
    r"bridge\.set_memory\s*\(",
]


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_bad_assistant_message(msg: Dict[str, Any]) -> bool:
    if str(msg.get("role", "")).strip() != "assistant":
        return False

    content = str(msg.get("content", "")).strip()
    if not content:
        return False

    for s in BAD_SNIPPETS:
        if s in content:
            return True

    for pattern in BAD_REGEXES:
        if re.search(pattern, content, flags=re.IGNORECASE):
            return True

    if "```python" in content and any(x in content for x in ["memory_bridge", "MemoryManager", "long_term.json"]):
        return True

    return False


def main() -> None:
    if not TARGET.exists():
        print(f"❌ 未找到文件: {TARGET}")
        return

    backup = backup_file(TARGET)
    data = read_json(TARGET)

    active = data.get("active_session", {}) or {}
    recent_messages = active.get("recent_messages", []) or []
    recent_actions = active.get("recent_actions", []) or []

    removed_messages: List[Dict[str, Any]] = []
    kept_messages: List[Dict[str, Any]] = []

    for msg in recent_messages:
        if isinstance(msg, dict) and is_bad_assistant_message(msg):
            removed_messages.append({
                "id": msg.get("id", ""),
                "timestamp": msg.get("timestamp", ""),
                "preview": str(msg.get("content", ""))[:180],
            })
        else:
            kept_messages.append(msg)

    cleaned_actions: List[Dict[str, Any]] = []
    for act in recent_actions:
        if not isinstance(act, dict):
            continue

        action_name = str(act.get("action_name", "")).strip()
        result_summary = str(act.get("result_summary", "")).strip()

        if action_name == "memory.consolidate":
            continue

        if action_name == "aicore.chat" and (
            "后端调用成功" in result_summary
            or "模型给出了不完整" in result_summary
            or "不可信" in result_summary
        ):
            continue

        cleaned_actions.append(act)

    active["recent_messages"] = kept_messages
    active["recent_actions"] = cleaned_actions
    active["session_summaries"] = []
    active["context_summary"] = ""
    data["active_session"] = active
    data["updated_at"] = datetime.now().astimezone().isoformat()

    write_json(TARGET, data)

    print("=" * 72)
    print("清理完成")
    print("=" * 72)
    print(f"backup: {backup}")
    print(f"removed_messages: {len(removed_messages)}")
    for item in removed_messages:
        print(f"- id={item['id']} | time={item['timestamp']} | preview={item['preview']}")


if __name__ == "__main__":
    main()
