#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import pprint
from typing import Any, Dict, List

from core.aicore.aicore import get_aicore_instance, reset_aicore_instance


pp = pprint.PrettyPrinter(width=120, sort_dicts=False)


def boot_aicore() -> Any:
    reset_aicore_instance()
    aicore = get_aicore_instance()

    bootstrap = getattr(aicore, "bootstrap_action_registry", None)
    if callable(bootstrap):
        try:
            info = bootstrap(force=True)
            print("=" * 96)
            print("bootstrap info")
            print("=" * 96)
            pp.pprint(info)
        except TypeError:
            info = bootstrap()
            print("=" * 96)
            print("bootstrap info")
            print("=" * 96)
            pp.pprint(info)

    return aicore


def first_step(result: Dict[str, Any]) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = result["execution"]["step_results"]
    return steps[0] if steps else {}


def run_case(aicore: Any, title: str, suggestion_text: str, runtime_context: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)

    result = aicore.process_suggestion_chain(
        suggestion_text,
        user_query=title,
        runtime_context=runtime_context,
        dry_run=False,
    )
    pp.pprint(result)

    step = first_step(result)
    output = step.get("output", {}) or {}

    print("-" * 96)
    print("step summary")
    print("-" * 96)
    print(f"status                = {step.get('status')}")
    print(f"action                = {step.get('action_name')}")
    print(f"source                = {output.get('source')}")
    print(f"view                  = {output.get('view')}")
    print(f"reason                = {step.get('reason')}")
    print(f"line_hint             = {output.get('line_hint')}")
    print(f"change_summary        = {output.get('change_summary')}")
    print(f"estimated_risk        = {output.get('estimated_risk')}")
    print(f"replace_count         = {output.get('replace_count')}")
    print(f"diff_truncated        = {output.get('diff_truncated')}")
    print(f"target_excerpt_before = {bool(output.get('target_excerpt_before') is not None)}")
    print(f"target_excerpt_after  = {bool(output.get('target_excerpt_after') is not None)}")
    print(f"context_before        = {bool(output.get('context_before') is not None)}")
    print(f"context_after         = {bool(output.get('context_after') is not None)}")

    return result


def assert_ok_preview_replace(result: Dict[str, Any]) -> bool:
    step = first_step(result)
    output = step.get("output", {}) or {}

    required = [
        "target_excerpt_before",
        "target_excerpt_after",
        "context_before",
        "context_after",
        "change_summary",
        "line_hint",
        "replace_count",
        "estimated_risk",
        "diff_preview",
    ]

    ok = step.get("status") == "ok"
    ok = ok and output.get("view") == "preview_replace_text"
    ok = ok and all(key in output for key in required)

    print(f"ASSERT preview_replace_ok = {'PASS' if ok else 'FAIL'}")
    return ok


def assert_fail_preview_replace(result: Dict[str, Any], expected_reason: str) -> bool:
    step = first_step(result)
    ok = step.get("status") == "failed" and step.get("reason") == expected_reason
    print(f"ASSERT preview_replace_fail({expected_reason}) = {'PASS' if ok else 'FAIL'}")
    return ok


def assert_ok_preview_append(result: Dict[str, Any]) -> bool:
    step = first_step(result)
    output = step.get("output", {}) or {}

    required = [
        "target_excerpt_before",
        "target_excerpt_after",
        "context_before",
        "context_after",
        "change_summary",
        "line_hint",
        "estimated_risk",
        "diff_preview",
    ]

    ok = step.get("status") == "ok"
    ok = ok and output.get("view") == "preview_append_text"
    ok = ok and all(key in output for key in required)

    print(f"ASSERT preview_append_ok = {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    aicore = boot_aicore()
    final_ok = True

    case1 = run_case(
        aicore=aicore,
        title="case_preview_replace_context_ok",
        suggestion_text="1. 调用 code_inserter.preview_replace_text 预演替换配置内容",
        runtime_context={
            "path": "config/global.yaml",
            "old": "modules: {}",
            "new": "modules:\\n  demo: true",
        },
    )
    final_ok = assert_ok_preview_replace(case1) and final_ok

    case2 = run_case(
        aicore=aicore,
        title="case_preview_replace_context_missing_pattern_should_fail",
        suggestion_text="1. 调用 code_inserter.preview_replace_text 预演替换配置内容",
        runtime_context={
            "path": "config/global.yaml",
            "old": "__definitely_not_exists__",
            "new": "demo",
        },
    )
    final_ok = assert_fail_preview_replace(case2, "pattern_not_found") and final_ok

    case3 = run_case(
        aicore=aicore,
        title="case_preview_append_context_ok",
        suggestion_text="1. 调用 code_inserter.preview_append_text 预演追加文本",
        runtime_context={
            "path": "config/global.yaml",
            "text": "\n# preview only\n",
        },
    )
    final_ok = assert_ok_preview_append(case3) and final_ok

    print("\n" + "=" * 96)
    print(f"FINAL = {'PASS' if final_ok else 'FAIL'}")
    print("=" * 96)


if __name__ == "__main__":
    main()
