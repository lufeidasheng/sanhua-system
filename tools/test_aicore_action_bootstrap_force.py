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
        out = []
        for x in raw:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                name = x.get("name") or x.get("action")
                if name:
                    out.append(str(name))
            else:
                out.append(str(x))
        return out
    return [str(raw)]


def main():
    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()

    print("=" * 88)
    print("before force bootstrap")
    print("=" * 88)
    before = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(before))
    for x in before:
        print(x)

    print("\n" + "=" * 88)
    print("force bootstrap info")
    print("=" * 88)
    info = aicore._bootstrap_action_registry(force=True)
    pprint(info)

    print("\n" + "=" * 88)
    print("after force bootstrap")
    print("=" * 88)
    after = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(after))
    for x in after:
        if any(k in x.lower() for k in ("sysmon", "system", "memory", "ai.", "health", "status")):
            print(x)

    print("\n" + "=" * 88)
    print("probes")
    print("=" * 88)
    for name in (
        "sysmon.status",
        "sysmon.metrics",
        "sysmon.health",
        "system.health_check",
        "system.status",
        "memory.search",
        "memory.recall",
        "ai.ask",
    ):
        try:
            got = dispatcher.get_action(name) if hasattr(dispatcher, "get_action") else None
        except Exception as e:
            got = f"<error: {e}>"
        print(f"{name:24s} -> {repr(got)}")


if __name__ == "__main__":
    main()
