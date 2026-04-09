#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import shutil
from pathlib import Path

SESSION_CACHE = Path("data/memory/session_cache.json")
BACKUP_PATH = Path("data/memory/session_cache.json.bak")

# 已知污染/泛化 assistant ID
BAD_IDS = {
    "41308bfa-5a25-455b-a80b-98c420288abc",
    "8bdd6c63-276f-4676-804b-a0a7c628f0be",
}

# 明显的“假路径 / 泛化教程”标记
BAD_MARKERS = [
    "src/memory/manager.py",
    "src/memory/bridge.py",
    "src/aicore/core.py",
    "run_aicore.py",
    "tests/test_memory_integration.py",
    "memory service",
    "http/grpc",
    "grpc",
    "rest",
    "微服务",
    "独立服务",
    "部署 memory layer",
    "注册插件",
]

# 当前真实结构关键词，命中太少说明偏泛
REAL_TERMS = [
    "core/memory_engine/memory_manager.py",
    "core/prompt_engine/prompt_memory_bridge.py",
    "core/aicore/extensible_aicore.py",
    "data/memory",
    "memorymanager",
    "promptmemorybridge",
    "extensibleaicore",
    "session_cache",
    "long_term",
    "persona",
    "三花聚顶",
    "aicore",
]


def short(s: str, n: int = 90) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")


def should_remove(msg: dict) -> tuple[bool, str]:
    msg_id = msg.get("id", "")
    role = msg.get("role", "")
    content = str(msg.get("content", ""))

    if role != "assistant":
        return False, ""

    if msg_id in BAD_IDS:
        return True, f"命中 BAD_IDS: {msg_id}"

    lower_content = content.lower()

    marker_hits = [m for m in BAD_MARKERS if m.lower() in lower_content]
    if marker_hits:
        return True, f"命中 BAD_MARKERS: {marker_hits[:3]}"

    real_hits = sum(1 for term in REAL_TERMS if term.lower() in lower_content)

    # 表格 + 教程味重 + 真实结构命中不足
    if "|" in content and "步骤" in content and real_hits < 3:
        return True, f"表格教程味过重，真实结构命中不足: real_hits={real_hits}"

    # 太长而且真实结构命中少
    if len(content) > 1800 and real_hits < 3:
        return True, f"内容过长且真实结构命中不足: len={len(content)}, real_hits={real_hits}"

    return False, ""


def main() -> None:
    if not SESSION_CACHE.exists():
        print(f"未找到文件: {SESSION_CACHE}")
        return

    data = json.loads(SESSION_CACHE.read_text(encoding="utf-8"))
    active = data.get("active_session", {})
    msgs = active.get("recent_messages", [])

    print("=" * 72)
    print("扫描 recent_messages")
    print("=" * 72)

    for i, m in enumerate(msgs, start=1):
        print(
            f"[{i}] id={m.get('id')} | role={m.get('role')} | "
            f"time={m.get('timestamp')} | content={short(str(m.get('content', '')))}"
        )

    cleaned = []
    removed = []

    for m in msgs:
        remove, reason = should_remove(m)
        if remove:
            removed.append({
                "id": m.get("id"),
                "role": m.get("role"),
                "reason": reason,
                "content_preview": short(str(m.get("content", "")), 120),
            })
        else:
            cleaned.append(m)

    if not removed:
        print("=" * 72)
        print("结果：没有发现匹配的污染 assistant 消息")
        print("说明：要么当前消息已经变了，要么这批消息未命中清理规则。")
        print("=" * 72)
        return

    # 先备份
    shutil.copy2(SESSION_CACHE, BACKUP_PATH)

    active["recent_messages"] = cleaned
    data["active_session"] = active

    SESSION_CACHE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 72)
    print("清理完成，已备份原文件到:", BACKUP_PATH)
    print("移除消息如下：")
    for item in removed:
        print(
            f"- id={item['id']} | reason={item['reason']} | "
            f"preview={item['content_preview']}"
        )
    print("=" * 72)


if __name__ == "__main__":
    main()#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path

SESSION_CACHE = Path("data/memory/session_cache.json")

BAD_IDS = {
    "8bdd6c63-276f-4676-804b-a0a7c628f0be",
}

BAD_MARKERS = [
    "src/memory/manager.py",
    "src/memory/bridge.py",
    "src/aicore/core.py",
    "run_aicore.py",
    "tests/test_memory_integration.py",
]


def main() -> None:
    if not SESSION_CACHE.exists():
        print(f"未找到文件: {SESSION_CACHE}")
        return

    data = json.loads(SESSION_CACHE.read_text(encoding="utf-8"))
    active = data.get("active_session", {})
    msgs = active.get("recent_messages", [])

    cleaned = []
    removed = []

    for m in msgs:
        msg_id = m.get("id")
        content = str(m.get("content", ""))

        should_remove = False

        if msg_id in BAD_IDS:
            should_remove = True

        if not should_remove and m.get("role") == "assistant":
            if any(marker in content for marker in BAD_MARKERS):
                should_remove = True

        if should_remove:
            removed.append(msg_id)
        else:
            cleaned.append(m)

    active["recent_messages"] = cleaned
    data["active_session"] = active

    SESSION_CACHE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("清理完成")
    print("移除消息 ID:", removed)


if __name__ == "__main__":
    main()
