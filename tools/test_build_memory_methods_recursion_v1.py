#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    print("=" * 72)
    print("test_build_memory_prompt")
    print("=" * 72)
    prompt = aicore.build_memory_prompt(
        "系统以后怎么记住我是鹏？",
        session_context={"source": "test_build_memory_methods_recursion_v1"},
    )
    print(type(prompt).__name__)
    print(len(str(prompt)))
    print(str(prompt)[:2000])

    print()
    print("=" * 72)
    print("test_build_memory_payload")
    print("=" * 72)
    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_build_memory_methods_recursion_v1"},
    )
    print(type(payload).__name__)
    print(payload.keys() if isinstance(payload, dict) else payload)

    final_prompt = str(payload.get("final_prompt", "")) if isinstance(payload, dict) else ""

    print()
    print("=" * 72)
    print("has_old_risk_block")
    print("=" * 72)
    print("[风险问题提示]" in final_prompt)

    print()
    print("=" * 72)
    print("has_compact_risk_block")
    print("=" * 72)
    print("[风险提示]" in final_prompt)

    print()
    print("=" * 72)
    print("final_prompt_length")
    print("=" * 72)
    print(len(final_prompt))

    print()
    print("=" * 72)
    print("final_prompt_preview")
    print("=" * 72)
    print(final_prompt[:3200])


if __name__ == "__main__":
    main()
