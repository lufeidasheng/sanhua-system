#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance, reset_aicore_instance


def main():
    reset_aicore_instance()

    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()
    info = aicore._bootstrap_action_registry(force=True)

    print("=" * 88)
    print("bootstrap info")
    print("=" * 88)
    pprint(info)

    print("\n" + "=" * 88)
    print("registered actions")
    print("=" * 88)
    try:
        actions = dispatcher.list_actions()
        if isinstance(actions, dict):
            actions = list(actions.keys())
        else:
            actions = list(actions or [])
    except Exception:
        actions = []

    actions = sorted(set(str(x) for x in actions))
    print("count =", len(actions))
    for x in actions:
        if "code_reviewer" in x or "code_reader" in x or "sysmon" in x or "system" in x:
            print(x)

    print("\n" + "=" * 88)
    print("probe get_action")
    print("=" * 88)
    for name in ("code_reviewer.review_text", "code_reviewer.review_file"):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:28s} -> {repr(got)}")

    print("\n" + "=" * 88)
    print("real execute via suggestion chain : review_text")
    print("=" * 88)
    review_text_result = aicore.process_suggestion_chain(
        suggestion_text="""
1. 调用 code_reviewer.review_text 审查这段代码
""",
        user_query="验证 code_reviewer.review_text",
        runtime_context={
            "text": """
print("debug")
try:
    x = 1 / 0
except Exception:
    pass
eval("1+1")
""".strip(),
        },
        dry_run=False,
    )
    pprint(review_text_result)

    print("\n" + "=" * 88)
    print("real execute via suggestion chain : review_file")
    print("=" * 88)
    review_file_result = aicore.process_suggestion_chain(
        suggestion_text="""
1. 调用 code_reviewer.review_file 审查 system_monitor 模块代码
""",
        user_query="验证 code_reviewer.review_file",
        runtime_context={
            "path": "modules/system_monitor/module.py",
            "max_chars": 5000,
        },
        dry_run=False,
    )
    pprint(review_file_result)

    print("\n" + "=" * 88)
    print("source check")
    print("=" * 88)
    for tag, result in (("review_text", review_text_result), ("review_file", review_file_result)):
        try:
            step = result["execution"]["step_results"][0]
            output = step.get("output", {})
            print(
                f"{tag}: status={step.get('status')} | "
                f"source={output.get('source')} | "
                f"view={output.get('view')} | "
                f"issue_count={output.get('issue_count')} | "
                f"risk_level={output.get('risk_level')} | "
                f"score={output.get('score')}"
            )
        except Exception as e:
            print(f"{tag}: parse error -> {e}")


if __name__ == "__main__":
    main()
