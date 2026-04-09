#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def temp_sysmon_status(**kwargs):
    return {
        "ok": True,
        "message": "临时注入的 sysmon.status 已执行",
        "kwargs": kwargs,
    }


def main():
    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()

    print("=" * 88)
    print("before register")
    print("=" * 88)
    print("dispatcher =", dispatcher)
    print("list_actions =", dispatcher.list_actions() if hasattr(dispatcher, "list_actions") else None)

    # 临时注册一个动作，验证 suggestion chain 真执行闭环
    dispatcher.register_action("sysmon.status", temp_sysmon_status)

    print("\n" + "=" * 88)
    print("after register")
    print("=" * 88)
    print("list_actions =", dispatcher.list_actions() if hasattr(dispatcher, "list_actions") else None)

    text = """
    1. 调用 sysmon.status 查看系统状态
    """

    result = aicore.process_suggestion_chain(
        suggestion_text=text,
        user_query="测试临时动作注册后的真实执行",
        dry_run=False,
    )

    print("\n" + "=" * 88)
    print("real execute result")
    print("=" * 88)
    pprint(result)


if __name__ == "__main__":
    main()
