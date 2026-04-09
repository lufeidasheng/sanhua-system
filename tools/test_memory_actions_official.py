#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _normalize_actions(raw: Any):
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


def _resolve_dispatcher(a: Any) -> Any:
    resolver = getattr(a, "_resolve_dispatcher", None)
    if callable(resolver):
        try:
            d = resolver()
            if d is not None:
                return d
        except Exception:
            pass

    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        try:
            obj = getattr(a, name, None)
            if obj is not None:
                return obj
        except Exception:
            continue
    return None


def _invoke_action(aicore: Any, action_name: str, runtime_context: Optional[Dict[str, Any]] = None, user_query: str = "") -> Dict[str, Any]:
    result = aicore.process_suggestion_chain(
        f"1. 调用 {action_name} 执行动作",
        user_query=user_query or action_name,
        runtime_context=runtime_context or {},
        dry_run=False,
    )
    step_results = ((result.get("execution") or {}).get("step_results") or [])
    step = step_results[0] if step_results else {}
    return {
        "raw": result,
        "step": step,
        "status": step.get("status"),
        "ok": step.get("status") == "ok",
        "output": step.get("output") or {},
    }


def _print_case(title: str) -> None:
    print()
    print("=" * 96)
    print(title)
    print("=" * 96)


def _print_step(label: str, step: Dict[str, Any]) -> None:
    output = step.get("output") or {}
    print(
        f"{label}: status={step.get('status')} | "
        f"action={step.get('action_name')} | "
        f"source={output.get('source')} | "
        f"view={output.get('view')} | "
        f"reason={step.get('reason')}"
    )


def main() -> int:
    root = _project_root()
    _ensure_sys_path(root)
    os.chdir(root)

    from core.aicore.aicore import get_aicore_instance
    from tools.memory_actions_official import register_actions, get_memory_actions_summary

    a = get_aicore_instance()

    if hasattr(a, "_bootstrap_action_registry"):
        bootstrap = a._bootstrap_action_registry(force=True)
    else:
        bootstrap = {"ok": False, "reason": "bootstrap_not_supported"}

    dispatcher = _resolve_dispatcher(a)

    reg = register_actions(dispatcher=dispatcher, aicore=a)
    summary = get_memory_actions_summary(dispatcher=dispatcher, aicore=a)

    _print_case("bootstrap info")
    pprint(bootstrap)

    _print_case("register memory actions")
    pprint(reg)

    _print_case("memory action summary")
    pprint(summary)

    _print_case("registered actions")
    try:
        names = sorted(set(_normalize_actions(dispatcher.list_actions())))
        print(f"count = {len(names)}")
        for name in names:
            if name.startswith("memory.") or name.startswith("sysmon.") or name.startswith("system.") or name.startswith("code_"):
                print(name)
    except Exception as e:
        print(f"list_actions failed: {e}")

    _print_case("probe get_action")
    for name in (
        "memory.health",
        "memory.snapshot",
        "memory.search",
        "memory.recall",
        "memory.add",
        "memory.append_chat",
        "memory.append_action",
    ):
        meta = None
        try:
            if hasattr(dispatcher, "get_action"):
                meta = dispatcher.get_action(name)
        except Exception:
            meta = None
        print(f"{name:<24} -> {meta}")

    marker = f"memory-test-{uuid.uuid4().hex[:8]}"

    # case 1
    _print_case("case_memory_health_should_ok")
    r1 = _invoke_action(a, "memory.health", {}, "case_memory_health_should_ok")
    pprint(r1["raw"])
    _print_step("step1", r1["step"])
    print("RESULT =", "PASS" if r1["ok"] else "FAIL")

    # case 2
    _print_case("case_memory_snapshot_should_ok")
    r2 = _invoke_action(a, "memory.snapshot", {}, "case_memory_snapshot_should_ok")
    pprint(r2["raw"])
    _print_step("step1", r2["step"])
    print("RESULT =", "PASS" if r2["ok"] else "FAIL")

    # case 3
    _print_case("case_memory_add_should_ok")
    add_ctx = {
        "content": {
            "type": "fact",
            "text": f"这是一条用于三花聚顶启动验收的测试记忆：{marker}",
            "marker": marker,
        },
        "memory_type": "fact",
        "importance": 0.91,
        "tags": ["memory_test", marker],
        "metadata": {"source": "test_memory_actions_official"},
    }
    r3 = _invoke_action(a, "memory.add", add_ctx, "case_memory_add_should_ok")
    pprint(r3["raw"])
    _print_step("step1", r3["step"])
    print("RESULT =", "PASS" if r3["ok"] else "FAIL")

    # case 4
    _print_case("case_memory_search_should_ok")
    search_ctx = {
        "query": marker,
        "limit": 5,
    }
    r4 = _invoke_action(a, "memory.search", search_ctx, "case_memory_search_should_ok")
    pprint(r4["raw"])
    _print_step("step1", r4["step"])
    print("RESULT =", "PASS" if r4["ok"] else "FAIL")

    # case 5
    _print_case("case_memory_recall_should_ok")
    recall_ctx = {
        "query": marker,
        "limit": 5,
    }
    r5 = _invoke_action(a, "memory.recall", recall_ctx, "case_memory_recall_should_ok")
    pprint(r5["raw"])
    _print_step("step1", r5["step"])
    print("RESULT =", "PASS" if r5["ok"] else "FAIL")

    # case 6
    _print_case("case_memory_append_chat_should_ok")
    chat_ctx = {
        "role": "user",
        "content": f"这是一次会话记忆追加测试：{marker}",
    }
    r6 = _invoke_action(a, "memory.append_chat", chat_ctx, "case_memory_append_chat_should_ok")
    pprint(r6["raw"])
    _print_step("step1", r6["step"])
    print("RESULT =", "PASS" if r6["ok"] else "FAIL")

    # case 7
    _print_case("case_memory_append_action_should_ok")
    action_ctx = {
        "action_name": "memory.search",
        "status": "success",
        "result_summary": f"search marker {marker}",
    }
    r7 = _invoke_action(a, "memory.append_action", action_ctx, "case_memory_append_action_should_ok")
    pprint(r7["raw"])
    _print_step("step1", r7["step"])
    print("RESULT =", "PASS" if r7["ok"] else "FAIL")

    results = [r1, r2, r3, r4, r5, r6, r7]
    final_ok = all(x["ok"] for x in results)

    print()
    print("=" * 96)
    print("FINAL =", "PASS" if final_ok else "FAIL")
    print("=" * 96)

    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
