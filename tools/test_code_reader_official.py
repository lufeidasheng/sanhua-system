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
        if any(k in x.lower() for k in ("sysmon", "system", "ai.", "memory", "code_reader", "status")):
            print(x)

    print("\n" + "=" * 88)
    print("probe get_action")
    print("=" * 88)
    for name in ("code_reader.exists", "code_reader.read_file", "code_reader.list_dir"):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:24s} -> {repr(got)}")

    print("\n" + "=" * 88)
    print("real execute via suggestion chain")
    print("=" * 88)
    result = aicore.process_suggestion_chain(
        suggestion_text="""
1. 调用 code_reader.exists 检查配置文件是否存在
2. 再调用 code_reader.read_file 读取配置文件
3. 再调用 code_reader.list_dir 查看 config 目录内容
""",
        user_query="验证正式 code_reader 模块动作",
        runtime_context={
            "path": "config/global.yaml",
            "limit": 20,
            "max_chars": 1500,
        },
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
