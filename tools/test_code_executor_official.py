#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import pprint
from typing import Any, Dict, List

from core.aicore.aicore import get_aicore_instance


def force_bootstrap(aicore: Any) -> Dict[str, Any]:
    for name in ("bootstrap_action_registry", "_bootstrap_action_registry"):
        if hasattr(aicore, name):
            fn = getattr(aicore, name)
            try:
                return fn(force=True)
            except TypeError:
                try:
                    return fn()
                except Exception as e:
                    return {"ok": False, "reason": f"{name} failed: {e}"}
            except Exception as e:
                return {"ok": False, "reason": f"{name} failed: {e}"}
    return {"ok": False, "reason": "bootstrap method not found"}


def get_registered_actions(dispatcher: Any) -> List[str]:
    if dispatcher is None:
        return []
    if hasattr(dispatcher, "list_actions"):
        try:
            data = dispatcher.list_actions()
            if isinstance(data, dict):
                return sorted(data.keys())
            if isinstance(data, list):
                return sorted(
                    [x for x in data if isinstance(x, str)]
                )
        except Exception:
            pass
    return []


def run_case(aicore: Any, name: str, suggestion_text: str, runtime_context: Dict[str, Any], expected_statuses: List[str]) -> bool:
    print("\n" + "=" * 96)
    print(name)
    print("=" * 96)

    result = aicore.process_suggestion_chain(
        suggestion_text,
        user_query=name,
        runtime_context=runtime_context,
        dry_run=False,
    )
    pprint.pprint(result, width=110)

    step_results = result.get("execution", {}).get("step_results", [])
    actual_statuses = [x.get("status") for x in step_results]

    print("-" * 96)
    print(f"expected_statuses = {expected_statuses}")
    print(f"actual_statuses   = {actual_statuses}")

    ok = actual_statuses == expected_statuses
    print(f"RESULT = {'PASS' if ok else 'FAIL'}")

    for idx, step in enumerate(step_results, start=1):
        output = step.get("output") or {}
        print(
            f"step{idx}: status={step.get('status')} | "
            f"action={step.get('action_name')} | "
            f"source={output.get('source')} | "
            f"view={output.get('view')} | "
            f"reason={step.get('reason')}"
        )

    return ok


if __name__ == "__main__":
    aicore = get_aicore_instance()
    bootstrap_info = force_bootstrap(aicore)

    dispatcher = getattr(aicore, "dispatcher", None)

    print("=" * 96)
    print("bootstrap info")
    print("=" * 96)
    pprint.pprint(bootstrap_info, width=110)

    print("\n" + "=" * 96)
    print("registered actions")
    print("=" * 96)
    actions = get_registered_actions(dispatcher)
    print(f"count = {len(actions)}")
    for name in actions:
        if name.startswith("code_executor.") or name.startswith("sysmon.") or name.startswith("system."):
            print(name)

    print("\n" + "=" * 96)
    print("probe get_action")
    print("=" * 96)
    for probe in ("code_executor.syntax_check", "code_executor.syntax_file"):
        meta = None
        if dispatcher is not None and hasattr(dispatcher, "get_action"):
            try:
                meta = dispatcher.get_action(probe)
            except Exception:
                meta = None
        print(f"{probe:<28} -> {meta}")

    overall = True

    overall = run_case(
        aicore=aicore,
        name="case_inline_ok_should_ok",
        suggestion_text="""
1. 调用 code_executor.syntax_check 检查这段代码语法
""",
        runtime_context={
            "text": 'print("ok")\nfor i in range(2):\n    print(i)\n',
        },
        expected_statuses=["ok"],
    ) and overall

    overall = run_case(
        aicore=aicore,
        name="case_inline_bad_should_fail",
        suggestion_text="""
1. 调用 code_executor.syntax_check 检查这段代码语法
""",
        runtime_context={
            "text": "def broken(\n    pass\n",
        },
        expected_statuses=["failed"],
    ) and overall

    overall = run_case(
        aicore=aicore,
        name="case_file_ok_should_ok",
        suggestion_text="""
1. 调用 code_executor.syntax_file 检查 system_monitor 模块语法
""",
        runtime_context={
            "path": "modules/system_monitor/module.py",
        },
        expected_statuses=["ok"],
    ) and overall

    print("\n" + "=" * 96)
    print(f"FINAL = {'PASS' if overall else 'FAIL'}")
    print("=" * 96)
