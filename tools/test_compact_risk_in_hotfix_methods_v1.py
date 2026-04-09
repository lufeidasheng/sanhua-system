#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_compact_risk_in_hotfix_methods_v1"},
    )

    final_prompt = str(payload.get("final_prompt", ""))

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
    print("prompt_length")
    print("=" * 72)
    print(len(final_prompt))

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:3200])


if __name__ == "__main__":
    main()
