#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def main():
    aicore = get_aicore_instance()

    text = """
1. 调用 sysmon.status 查看系统状态
"""

    # 先 dry-run 看计划
    dry_result = aicore.process_suggestion_chain(
        suggestion_text=text,
        user_query="低风险真实执行前预演",
        dry_run=True,
    )

    print("=" * 88)
    print("第一阶段：dry-run 预演")
    print("=" * 88)
    pprint(dry_result)

    decision = dry_result.get("decision", {})
    rejected = decision.get("rejected_items", [])
    review = decision.get("review_items", [])
    approved = decision.get("approved_items", [])

    if rejected:
        print("\n[STOP] 存在 rejected_items，终止真实执行。")
        return

    if review:
        print("\n[STOP] 存在 review_items，终止真实执行。")
        return

    if not approved:
        print("\n[STOP] 没有 approved_items，终止真实执行。")
        return

    approved_action_names = [item.get("action_name") for item in approved if item.get("action_name")]
    print("\napproved_action_names =", approved_action_names)

    # 再真实执行
    real_result = aicore.process_suggestion_chain(
        suggestion_text=text,
        user_query="低风险真实执行",
        dry_run=False,
    )

    print("\n" + "=" * 88)
    print("第二阶段：真实执行结果")
    print("=" * 88)
    pprint(real_result)


if __name__ == "__main__":
    main()
