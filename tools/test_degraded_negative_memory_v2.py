#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    query = "系统以后怎么记住我是鹏？"

    aicore._record_degraded_pattern(query, "test degraded v2 #1")
    aicore._record_degraded_pattern(query, "test degraded v2 #2")

    payload = aicore.build_memory_payload(
        user_input=query,
        session_context={"source": "test_degraded_negative_memory_v2"},
    )

    print("=" * 72)
    print("degraded_memory_runtime")
    print("=" * 72)
    print(aicore.get_status().get("degraded_memory_runtime"))

    print()
    print("=" * 72)
    print("has_risk_block")
    print("=" * 72)
    print("[风险问题提示]" in payload.get("final_prompt", ""))

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(payload.get("final_prompt", "")[:4000])


if __name__ == "__main__":
    main()
