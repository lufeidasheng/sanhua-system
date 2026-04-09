#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    print("=" * 72)
    print("maintenance_runtime before")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("maintenance_runtime", {}), ensure_ascii=False, indent=2))

    for i in range(3):
        aicore.record_action_memory(
            action_name="aicore.chat",
            status="degraded",
            result_summary=f"test degraded #{i+1}",
        )

    print()
    print("=" * 72)
    print("maintenance_runtime after")
    print("=" * 72)
    print(json.dumps(aicore.get_status().get("maintenance_runtime", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
