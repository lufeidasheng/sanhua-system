#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pprint import pprint

from core.aicore.aicore import get_aicore_instance, reset_aicore_instance


def run_case(aicore, name, suggestion_text, runtime_context, expected_statuses):
    print("\n" + "=" * 96)
    print(name)
    print("=" * 96)

    result = aicore.process_suggestion_chain(
        suggestion_text=suggestion_text,
        user_query=name,
        runtime_context=runtime_context,
        dry_run=False,
    )
    pprint(result)

    actual_statuses = [x.get("status") for x in result.get("execution", {}).get("step_results", [])]
    print("-" * 96)
    print("expected_statuses =", expected_statuses)
    print("actual_statuses   =", actual_statuses)

    ok = actual_statuses == expected_statuses
    print("RESULT =", "PASS" if ok else "FAIL")

    for idx, step in enumerate(result.get("execution", {}).get("step_results", []), start=1):
        output = step.get("output", {})
        print(
            f"step{idx}: status={step.get('status')} | "
            f"action={step.get('action_name')} | "
            f"source={output.get('source')} | "
            f"view={output.get('view')} | "
            f"reason={step.get('reason')}"
        )

    return ok


def main():
    reset_aicore_instance()
    aicore = get_aicore_instance()
    boot = aicore._bootstrap_action_registry(force=True)

    print("=" * 96)
    print("bootstrap info")
    print("=" * 96)
    pprint(boot)

    all_ok = True

    # 1) 读取不存在的文件：应该 failed
    all_ok &= run_case(
        aicore,
        "case_missing_file_should_fail",
        """
1. 调用 code_reader.read_file 读取不存在的配置文件
""",
        {
            "path": "config/__definitely_not_exists__.yaml",
            "max_chars": 1200,
        },
        ["failed"],
    )

    # 2) 把文件当目录列出：应该 failed
    all_ok &= run_case(
        aicore,
        "case_list_dir_on_file_should_fail",
        """
1. 调用 code_reader.list_dir 查看 config/global.yaml 目录内容
""",
        {
            "path": "config/global.yaml",
            "limit": 20,
        },
        ["failed"],
    )

    # 3) 正常成功用例：应该 ok
    all_ok &= run_case(
        aicore,
        "case_success_should_ok",
        """
1. 调用 sysmon.status 查看系统状态
2. 再调用 system.status 查看系统状态
""",
        {},
        ["ok", "ok"],
    )

    print("\n" + "=" * 96)
    print("FINAL =", "PASS" if all_ok else "FAIL")
    print("=" * 96)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
