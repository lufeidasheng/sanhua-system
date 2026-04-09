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


def run_case(
    aicore: Any,
    name: str,
    suggestion_text: str,
    runtime_context: Dict[str, Any],
    expected_statuses: List[str],
) -> bool:
    print("\n" + "=" * 96)
    print(name)
    print("=" * 96)

    result = aicore.process_suggestion_chain(
        suggestion_text,
        user_query=name,
        runtime_context=runtime_context,
        dry_run=False,
    )
    pprint.pprint(result, width=120)

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
    pprint.pprint(bootstrap_info, width=120)

    print("\n" + "=" * 96)
    print("probe get_action")
    print("=" * 96)
    for probe in (
        "code_inserter.preview_replace_text",
        "code_inserter.preview_append_text",
    ):
        meta = None
        if dispatcher is not None and hasattr(dispatcher, "get_action"):
            try:
                meta = dispatcher.get_action(probe)
            except Exception:
                meta = None
        print(f"{probe:<34} -> {meta}")

    overall = True

    overall = run_case(
        aicore=aicore,
        name="case_preview_replace_ok_should_ok",
        suggestion_text="""
1. 调用 code_inserter.preview_replace_text 预演替换配置内容
""",
        runtime_context={
            "path": "config/global.yaml",
            "old": "modules: {}",
            "new": "modules:\\n  demo: true",
        },
        expected_statuses=["ok"],
    ) and overall

    overall = run_case(
        aicore=aicore,
        name="case_preview_replace_missing_pattern_should_fail",
        suggestion_text="""
1. 调用 code_inserter.preview_replace_text 预演替换配置内容
""",
        runtime_context={
            "path": "config/global.yaml",
            "old": "__definitely_not_exists__",
            "new": "demo",
        },
        expected_statuses=["failed"],
    ) and overall

    overall = run_case(
        aicore=aicore,
        name="case_preview_append_ok_should_ok",
        suggestion_text="""
1. 调用 code_inserter.preview_append_text 预演追加文本
""",
        runtime_context={
            "path": "config/global.yaml",
            "text": "\\n# preview only\\n",
        },
        expected_statuses=["ok"],
    ) and overall

    print("\n" + "=" * 96)
    print(f"FINAL = {'PASS' if overall else 'FAIL'}")
    print("=" * 96)
