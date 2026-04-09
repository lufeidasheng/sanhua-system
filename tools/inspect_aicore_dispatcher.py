#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def main():
    aicore = get_aicore_instance()

    if hasattr(aicore, "_resolve_dispatcher"):
        dispatcher = aicore._resolve_dispatcher()
    else:
        dispatcher = getattr(aicore, "dispatcher", None)

    print("=" * 88)
    print("dispatcher object")
    print("=" * 88)
    print("type(dispatcher) =", type(dispatcher))
    print("repr(dispatcher) =", repr(dispatcher))

    if dispatcher is None:
        print("\n[STOP] dispatcher is None")
        return

    names = sorted([n for n in dir(dispatcher) if not n.startswith("_")])

    print("\n" + "=" * 88)
    print("public attrs/methods")
    print("=" * 88)
    for n in names:
        try:
            v = getattr(dispatcher, n)
            print(f"{n:32s} -> {'callable' if callable(v) else type(v).__name__}")
        except Exception as e:
            print(f"{n:32s} -> <error: {e}>")

    print("\n" + "=" * 88)
    print("candidate methods")
    print("=" * 88)
    candidates = [
        "call_action",
        "dispatch_action",
        "execute_action",
        "dispatch",
        "call",
        "invoke",
        "run",
        "run_action",
        "do_action",
        "trigger",
        "trigger_action",
        "emit",
        "match_action",
        "has_action",
        "get_action",
        "list_actions",
    ]
    for name in candidates:
        print(f"{name:20s} -> {hasattr(dispatcher, name)}")

    print("\n" + "=" * 88)
    print("aicore attrs")
    print("=" * 88)
    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        print(f"{name:20s} -> {hasattr(aicore, name)} | {type(getattr(aicore, name, None))}")


if __name__ == "__main__":
    main()
