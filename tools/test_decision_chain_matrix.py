#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


CASES = {
    "case_low_risk": """
1. 调用 sysmon.status 查看系统状态
2. 调用 ai.ask 分析当前错误原因
""",
    "case_mixed_risk": """
1. 调用 sysmon.status 查看系统状态
2. 如需修改配置文件，先人工确认
3. 不要直接执行 shell
""",
    "case_high_risk": """
1. 先执行 reboot 重启系统
2. 再调用 sysmon.status 检查状态
""",
}


def print_brief(name: str, result: dict) -> None:
    decision = result.get("decision", {})
    plan = result.get("plan", {})
    execution = result.get("execution", {})

    print(f"\n{'=' * 88}")
    print(f"[{name}]")
    print("-" * 88)
    print("overall_verdict :", decision.get("overall_verdict"))
    print("risk_level      :", decision.get("risk_level"))
    print("approved_items  :", len(decision.get("approved_items", [])))
    print("review_items    :", len(decision.get("review_items", [])))
    print("rejected_items  :", len(decision.get("rejected_items", [])))
    print("plan_executable :", plan.get("executable"))
    print("execution_mode  :", execution.get("mode"))
    print("execution_ok    :", execution.get("success"))
    print("-" * 88)

    print("item_decisions:")
    for item in decision.get("item_decisions", []):
        print(f"  - {item.get('item_id')}: {item.get('verdict')} | reasons={item.get('reasons')}")

    print("-" * 88)
    print("steps:")
    for step in plan.get("steps", []):
        print(f"  - {step.get('step_id')}: {step.get('kind')} | {step.get('title')}")

    print("-" * 88)
    print("step_results:")
    for sr in execution.get("step_results", []):
        print(f"  - {sr.get('step_id')}: {sr.get('status')} | {sr.get('title')}")


def main():
    aicore = get_aicore_instance()

    for name, text in CASES.items():
        result = aicore.process_suggestion_chain(
            suggestion_text=text,
            user_query=f"测试 {name}",
            dry_run=True,
        )
        print_brief(name, result)

    print(f"\n{'=' * 88}")
    print("完整结果样例（最后一个 case）")
    print("-" * 88)
    pprint(result)


if __name__ == "__main__":
    main()
