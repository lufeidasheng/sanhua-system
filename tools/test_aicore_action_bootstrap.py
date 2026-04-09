#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def normalize_actions(raw):
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.keys())
    if isinstance(raw, (list, tuple, set)):
        return [str(x) for x in raw]
    return [str(raw)]


def main():
    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()

    print("=" * 88)
    print("dispatcher")
    print("=" * 88)
    print(type(dispatcher))

    print("\n" + "=" * 88)
    print("bootstrap info")
    print("=" * 88)
    if hasattr(aicore, "_bootstrap_action_registry"):
        info = aicore._bootstrap_action_registry(force=False)
        pprint(info)
    else:
        print("no _bootstrap_action_registry")

    print("\n" + "=" * 88)
    print("actions")
    print("=" * 88)
    actions = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(actions))
    for x in actions:
        if any(k in x.lower() for k in ("sysmon", "system", "ai.", "memory", "health", "status")):
            print(x)

    print("\n" + "=" * 88)
    print("probes")
    print("=" * 88)
    for name in ("sysmon.status", "sysmon.metrics", "system.health_check", "ai.ask"):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:24s} -> {repr(got)}")


if __name__ == "__main__":
    main()
