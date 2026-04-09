#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path

from core.aicore.aicore import get_aicore_instance


def read_patterns(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(data, dict):
        patterns = data.get("patterns", [])
        return patterns if isinstance(patterns, list) else []

    if isinstance(data, list):
        return data

    return []


def read_count(path: Path, query: str) -> int:
    query = str(query or "").strip()
    for item in read_patterns(path):
        if not isinstance(item, dict):
            continue
        if str(item.get("query_norm", "")).strip() == query:
            return int(item.get("count", 0) or 0)
        if str(item.get("query_excerpt", "")).strip() == query:
            return int(item.get("count", 0) or 0)
    return 0


def main() -> None:
    aicore = get_aicore_instance()

    runtime_before = aicore.get_status().get("degraded_memory_runtime", {})
    path = Path(runtime_before.get("path") or "data/memory/degraded_patterns.json")

    query = "系统以后怎么记住我是鹏？"
    before = read_count(path, query)

    print("=" * 72)
    print("before_count")
    print("=" * 72)
    print(before)

    # 连续记录 3 次；按 hardening 逻辑，冷却窗口内最多只应 +1
    recorder = getattr(aicore, "_record_degraded_pattern", None)
    if recorder is None:
        recorder = getattr(aicore, "record_degraded_pattern", None)

    if not callable(recorder):
        print()
        print("❌ 未找到 degraded pattern record 接口")
        return

    recorder(query, "hardening test #1")
    recorder(query, "hardening test #2")
    recorder(query, "hardening test #3")

    after = read_count(path, query)
    runtime_after = aicore.get_status().get("degraded_memory_runtime", {})

    print()
    print("=" * 72)
    print("after_count")
    print("=" * 72)
    print(after)

    print()
    print("=" * 72)
    print("delta_should_be_0_or_1")
    print("=" * 72)
    print(after - before)

    print()
    print("=" * 72)
    print("degraded_memory_runtime")
    print("=" * 72)
    print(json.dumps(runtime_after, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
