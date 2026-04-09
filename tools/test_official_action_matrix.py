#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance, reset_aicore_instance


def run_case(aicore, name, suggestion_text, runtime_context=None):
    print("\n" + "=" * 96)
    print(name)
    print("=" * 96)
    result = aicore.process_suggestion_chain(
        suggestion_text=suggestion_text,
        user_query=name,
        runtime_context=runtime_context or {},
        dry_run=False,
    )
    pprint(result)

    print("-" * 96)
    try:
        step_results = result["execution"]["step_results"]
        for idx, step in enumerate(step_results, start=1):
            output = step.get("output", {})
            print(
                f"step{idx}: status={step.get('status')} | "
                f"action={step.get('action_name')} | "
                f"source={output.get('source')} | "
                f"view={output.get('view')} | "
                f"reason={step.get('reason')}"
            )
    except Exception as e:
        print("step parse error:", e)


def main():
    reset_aicore_instance()
    aicore = get_aicore_instance()
    aicore._bootstrap_action_registry(force=True)

    run_case(
        aicore,
        "case_sysmon",
        """
1. 调用 sysmon.status 查看系统状态
""",
    )

    run_case(
        aicore,
        "case_system_control",
        """
1. 调用 system.health_check 检查系统健康
2. 再调用 system.status 查看系统状态
""",
    )

    run_case(
        aicore,
        "case_code_reader_file",
        """
1. 调用 code_reader.exists 检查配置文件是否存在
2. 再调用 code_reader.read_file 读取配置文件
""",
        runtime_context={
            "path": "config/global.yaml",
            "max_chars": 1500,
        },
    )

    run_case(
        aicore,
        "case_code_reader_dir",
        """
1. 调用 code_reader.list_dir 查看 config 目录内容
""",
        runtime_context={
            "path": "config",
            "limit": 20,
        },
    )


if __name__ == "__main__":
    main()
