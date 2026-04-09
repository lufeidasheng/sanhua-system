#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_prompt_slim_profile"},
    )
    final_prompt = payload.get("final_prompt", "")

    print("=" * 72)
    print("has_identity_anchor")
    print("=" * 72)
    print("[身份锚点]" in final_prompt)

    print()
    print("=" * 72)
    print("has_user_profile")
    print("=" * 72)
    print("[用户画像]" in final_prompt)

    print()
    print("=" * 72)
    print("prompt_length")
    print("=" * 72)
    print(len(final_prompt))

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:4000])


if __name__ == "__main__":
    main()
