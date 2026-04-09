#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    print("=" * 72)
    print("identity_anchor")
    print("=" * 72)
    print(json.dumps(aicore.get_user_identity(), ensure_ascii=False, indent=2))

    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_identity_anchor"},
    )

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(payload.get("final_prompt", "")[:3000])

    print()
    print("=" * 72)
    print("status.identity_anchor")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("identity_anchor", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
