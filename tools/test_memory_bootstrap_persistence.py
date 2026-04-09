#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def run_action(aicore: Any, action_name: str, runtime_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    result = aicore.process_suggestion_chain(
        f"1. 调用 {action_name} 执行动作",
        user_query=f"bootstrap_persistence::{action_name}",
        runtime_context=runtime_context or {},
        dry_run=False,
    )
    step_results = ((result.get("execution") or {}).get("step_results") or [])
    step = step_results[0] if step_results else {}
    return {
        "ok": step.get("status") == "ok",
        "step": step,
        "raw": result,
    }


def summarize_step(step: Dict[str, Any]) -> str:
    output = step.get("output") or {}
    return (
        f"status={step.get('status')} | "
        f"action={step.get('action_name')} | "
        f"source={output.get('source')} | "
        f"view={output.get('view')} | "
        f"reason={step.get('reason')}"
    )


def main() -> int:
    root = project_root_from_here()
    ensure_sys_path(root)
    os.chdir(root)

    from core.aicore.aicore import get_aicore_instance, reset_aicore_instance  # noqa

    print("=" * 96)
    print("TEST MEMORY BOOTSTRAP PERSISTENCE")
    print("=" * 96)

    # 关键点：不手动 import tools.memory_actions_official，也不手动运行注册脚本
    reset_aicore_instance()
    aicore = get_aicore_instance()

    bootstrap_info = None
    if hasattr(aicore, "_bootstrap_action_registry"):
        bootstrap_info = aicore._bootstrap_action_registry(force=True)

    print("\n[bootstrap info]")
    pprint(bootstrap_info)

    dispatcher = aicore._resolve_dispatcher() if hasattr(aicore, "_resolve_dispatcher") else None
    if dispatcher is None:
        print("\n[FAIL] dispatcher_not_ready")
        return 2

    list_actions = getattr(dispatcher, "list_actions", None)
    get_action = getattr(dispatcher, "get_action", None)

    all_actions: List[str] = []
    if callable(list_actions):
        try:
            raw = list_actions()
            if isinstance(raw, dict):
                all_actions = sorted(str(x) for x in raw.keys())
            elif isinstance(raw, (list, tuple, set)):
                out = []
                for item in raw:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        out.append(str(item.get("name") or item.get("action") or item))
                    else:
                        out.append(str(item))
                all_actions = sorted(set(out))
        except Exception:
            all_actions = []

    print("\n[action_count]")
    print(len(all_actions))

    print("\n[registered actions - filtered]")
    for name in all_actions:
        if name.startswith(("memory.", "sysmon.", "system.", "code_")):
            print(name)

    required = [
        "memory.health",
        "memory.snapshot",
        "memory.search",
        "memory.recall",
        "memory.add",
        "memory.append_chat",
        "memory.append_action",
    ]

    probes = {}
    for name in required:
        try:
            probes[name] = callable(get_action) and (get_action(name) is not None)
        except Exception:
            probes[name] = False

    print("\n[probes]")
    for name, ok in probes.items():
        print(f"{name:<24} -> {ok}")

    marker = f"memory-bootstrap-{uuid.uuid4().hex[:8]}"

    cases = [
        ("memory.health", {}),
        ("memory.snapshot", {}),
        ("memory.add", {
            "content": {
                "marker": marker,
                "text": f"这是一条 bootstrap 持久化测试记忆：{marker}",
                "type": "fact",
            },
            "memory_type": "fact",
            "importance": 0.88,
            "tags": ["bootstrap_test", marker],
            "metadata": {"source": "test_memory_bootstrap_persistence"},
        }),
        ("memory.search", {
            "query": marker,
            "limit": 5,
        }),
        ("memory.recall", {
            "query": marker,
            "limit": 5,
        }),
        ("memory.append_chat", {
            "role": "user",
            "content": f"这是一次 bootstrap 自动注册测试：{marker}",
        }),
        ("memory.append_action", {
            "action_name": "memory.search",
            "status": "success",
            "result_summary": f"search marker {marker}",
        }),
    ]

    print("\n[smoke]")
    smoke_ok = True
    for action_name, ctx in cases:
        res = run_action(aicore, action_name, ctx)
        step = res["step"]
        ok = res["ok"]
        smoke_ok = smoke_ok and ok
        print(f"{action_name:<24} -> {summarize_step(step)}")

    required_ok = all(probes.values())

    print("\n[summary]")
    print(f"required_actions_ok -> {required_ok}")
    print(f"smoke_ok            -> {smoke_ok}")

    final_ok = required_ok and smoke_ok
    print("\nFINAL =", "PASS" if final_ok else "FAIL")
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
