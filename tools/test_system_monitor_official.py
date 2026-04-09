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
    # 关键：重置单例，避免沿用旧 dispatcher 状态
    reset_aicore_instance()

    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()

    # 强制再跑一次 bootstrap，确保正式模块有机会注册
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
    for name in ("sysmon.status", "sysmon.metrics", "sysmon.health"):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:18s} -> {repr(got)}")

    print("\n" + "=" * 88)
    print("real execute via suggestion chain")
    print("=" * 88)
    result = aicore.process_suggestion_chain(
        suggestion_text="""
1. 调用 sysmon.status 查看系统状态
""",
        user_query="验证正式 system_monitor 模块动作",
        dry_run=False,
    )
    pprint(result)

    print("\n" + "=" * 88)
    print("source check")
    print("=" * 88)
    try:
        step_results = result["execution"]["step_results"]
        if step_results:
            output = step_results[0].get("output", {})
            print("output.source =", output.get("source"))
            print("output.view   =", output.get("view"))
    except Exception as e:
        print("source check error:", e)


if __name__ == "__main__":
    main()
