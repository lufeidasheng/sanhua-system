#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from core.aicore.aicore import get_aicore_instance


KEYWORDS = [
    "sysmon",
    "status",
    "health",
    "metric",
    "monitor",
    "system",
]


def normalize_actions(raw):
    if raw is None:
        return []

    if isinstance(raw, dict):
        return list(raw.keys())

    if isinstance(raw, (list, tuple, set)):
        out = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("action")
                if name:
                    out.append(str(name))
            else:
                out.append(str(item))
        return out

    return [str(raw)]


def main():
    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()

    print("=" * 88)
    print("dispatcher type")
    print("=" * 88)
    print(type(dispatcher))

    if dispatcher is None:
        print("[STOP] dispatcher is None")
        return

    print("\n" + "=" * 88)
    print("all actions")
    print("=" * 88)
    try:
        raw = dispatcher.list_actions()
        actions = sorted(set(normalize_actions(raw)))
    except Exception as e:
        print(f"[ERROR] list_actions() failed: {e}")
        return

    print(f"总动作数: {len(actions)}")
    for name in actions:
        print(name)

    print("\n" + "=" * 88)
    print("keyword filtered actions")
    print("=" * 88)
    matched = []
    for name in actions:
        lower = name.lower()
        if any(k in lower for k in KEYWORDS):
            matched.append(name)

    if not matched:
        print("未找到匹配 sysmon/status/health/metrics 等关键词的动作")
    else:
        for name in matched:
            print(f"\n{name}")
            try:
                if hasattr(dispatcher, "get_aliases_for_action"):
                    aliases = dispatcher.get_aliases_for_action(name)
                    print("  aliases =", aliases)
            except Exception as e:
                print(f"  aliases = <error: {e}>")

    print("\n" + "=" * 88)
    print("direct probes")
    print("=" * 88)
    probes = [
        "sysmon.status",
        "sysmon.metrics",
        "sysmon.health",
        "system.health_check",
        "system.status",
        "health.check",
    ]

    for probe in probes:
        print(f"\nprobe: {probe}")
        try:
            if hasattr(dispatcher, "get_action"):
                got = dispatcher.get_action(probe)
                print("  get_action ->", repr(got))
        except Exception as e:
            print("  get_action -> ERROR:", e)

        try:
            if hasattr(dispatcher, "match_action"):
                matched = dispatcher.match_action(probe)
                print("  match_action ->", repr(matched))
        except Exception as e:
            print("  match_action -> ERROR:", e)


if __name__ == "__main__":
    main()
