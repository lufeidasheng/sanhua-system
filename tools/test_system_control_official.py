#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance, reset_aicore_instance


def normalize_actions(raw):
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.keys())
    if isinstance(raw, (list, tuple, set)):
        return [str(x) for x in raw]
    return [str(raw)]


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
    actions = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(actions))
    for x in actions:
        if any(k in x.lower() for k in ("sysmon", "system", "ai.", "memory", "health", "status")):
            print(x)

    print("\n" + "=" * 88)
    print("probe get_action")
    print("=" * 88)
    for name in ("system.health_check", "system.status", "sysmon.status"):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:20s} -> {repr(got)}")

    print("\n" + "=" * 88)
    print("real execute via suggestion chain")
    print("=" * 88)
    result = aicore.process_suggestion_chain(
        suggestion_text="""
1. 调用 system.health_check 检查系统健康
2. 再调用 system.status 查看系统状态
""",
        user_query="验证正式 system_control 模块动作",
        dry_run=False,
    )
    pprint(result)

    print("\n" + "=" * 88)
    print("source check")
    print("=" * 88)
    try:
        for idx, step in enumerate(result["execution"]["step_results"], start=1):
            output = step.get("output", {})
            print(f"step{idx}.source =", output.get("source"))
            print(f"step{idx}.view   =", output.get("view"))
    except Exception as e:
        print("source check error:", e)


if __name__ == "__main__":
    main()
