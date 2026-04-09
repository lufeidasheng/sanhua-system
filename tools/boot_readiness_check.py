#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List


def log(*args, **kwargs) -> None:
    print(*args, **kwargs)


def ensure_sys_path(root: Path) -> None:
    root_str = str(root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def normalize_actions(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [str(k) for k in raw.keys()]
    if isinstance(raw, (list, tuple, set)):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("action")
                if name:
                    out.append(str(name))
                else:
                    out.append(str(item))
            else:
                out.append(str(item))
        return out
    return [str(raw)]


def resolve_dispatcher(aicore: Any) -> Any:
    resolver = getattr(aicore, "_resolve_dispatcher", None)
    if callable(resolver):
        try:
            dispatcher = resolver()
            if dispatcher is not None:
                return dispatcher
        except Exception:
            pass

    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        try:
            obj = getattr(aicore, name, None)
            if obj is not None:
                return obj
        except Exception:
            continue

    return None


def call_action_via_chain(
    aicore: Any,
    action_name: str,
    runtime_context: Dict[str, Any] | None = None,
    user_query: str = "",
) -> Dict[str, Any]:
    runtime_context = runtime_context or {}
    result = aicore.process_suggestion_chain(
        f"1. 调用 {action_name} 执行动作",
        user_query=user_query or f"boot_readiness:{action_name}",
        runtime_context=runtime_context,
        dry_run=False,
    )
    step_results = ((result.get("execution") or {}).get("step_results") or [])
    step = step_results[0] if step_results else {}
    return {
        "ok": step.get("status") == "ok",
        "step": step,
        "raw": result,
    }


def fmt_step_line(name: str, result: Dict[str, Any]) -> str:
    step = result.get("step") or {}
    output = step.get("output") or {}
    return (
        f"{name:<32} -> "
        f"ok={result.get('ok')} "
        f"status={step.get('status')} "
        f"source={output.get('source')} "
        f"view={output.get('view')} "
        f"reason={step.get('reason')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="三花聚顶启动就绪检查")
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        log(f"[ERROR] root not found: {root}")
        return 2

    ensure_sys_path(root)
    os.chdir(root)

    try:
        from core.aicore.aicore import get_aicore_instance
    except Exception:
        log("[ERROR] import get_aicore_instance failed")
        log(traceback.format_exc())
        return 3

    try:
        aicore = get_aicore_instance()
    except Exception:
        log("[ERROR] get_aicore_instance failed")
        log(traceback.format_exc())
        return 4

    bootstrap_info = None
    try:
        if hasattr(aicore, "_bootstrap_action_registry"):
            bootstrap_info = aicore._bootstrap_action_registry(force=True)
    except Exception as e:
        bootstrap_info = {"ok": False, "reason": str(e)}

    dispatcher = resolve_dispatcher(aicore)
    if dispatcher is None:
        log("================================================================================================")
        log("BOOT READINESS CHECK")
        log("================================================================================================")
        log("overall        : BOOT_FAIL")
        log("reason         : dispatcher_not_ready")
        log("================================================================================================")
        return 5

    try:
        action_names = sorted(set(normalize_actions(dispatcher.list_actions())))
    except Exception:
        action_names = []

    action_set = set(action_names)

    capability_map = {
        "memory_manager": hasattr(aicore, "memory_manager"),
        "prompt_memory_bridge": hasattr(aicore, "prompt_memory_bridge"),
        "process_suggestion_chain": hasattr(aicore, "process_suggestion_chain"),
        "safe_apply_change_set": hasattr(aicore, "safe_apply_change_set"),
        "evolve_file_replace": hasattr(aicore, "evolve_file_replace"),
    }

    required_actions = [
        "ai.ask",
        "sysmon.status",
        "system.status",
        "code_reader.read_file",
        "code_reviewer.review_text",
        "code_executor.syntax_check",
        "code_inserter.preview_replace_text",
        "memory.health",
        "memory.snapshot",
        "memory.search",
        "memory.recall",
    ]

    action_presence = {name: (name in action_set) for name in required_actions}

    smoke_specs = [
        ("sysmon.status", {}, "check sysmon"),
        ("system.status", {}, "check system status"),
        ("code_reader.read_file", {"path": "config/global.yaml", "max_chars": 1200}, "read config"),
        ("code_executor.syntax_check", {"text": "def demo():\n    return 1\n"}, "syntax check"),
        ("code_inserter.preview_append_text", {"path": "config/global.yaml", "text": "\n# boot readiness preview only\n"}, "preview append"),
        ("memory.health", {}, "memory health"),
        ("memory.snapshot", {}, "memory snapshot"),
        ("memory.search", {"query": "三花聚顶", "limit": 5}, "memory search"),
    ]

    smoke_results: Dict[str, Dict[str, Any]] = {}
    for action_name, ctx, user_query in smoke_specs:
        if action_name not in action_set:
            smoke_results[action_name] = {
                "ok": False,
                "step": {
                    "status": "missing",
                    "action_name": action_name,
                    "reason": "action_not_registered",
                    "output": {},
                },
                "raw": None,
            }
            continue

        try:
            smoke_results[action_name] = call_action_via_chain(
                aicore,
                action_name,
                runtime_context=ctx,
                user_query=user_query,
            )
        except Exception as e:
            smoke_results[action_name] = {
                "ok": False,
                "step": {
                    "status": "failed",
                    "action_name": action_name,
                    "reason": str(e),
                    "output": {},
                },
                "raw": None,
            }

    critical_capabilities_ok = all(capability_map.values())
    critical_actions_ok = all(action_presence.values())
    critical_smoke_ok = all(v.get("ok") for v in smoke_results.values())

    overall = "BOOT_OK" if (
        critical_capabilities_ok and critical_actions_ok and critical_smoke_ok
    ) else "BOOT_DEGRADED"

    log("================================================================================================")
    log("BOOT READINESS CHECK")
    log("================================================================================================")
    log(f"overall        : {overall}")
    log(f"action_count   : {len(action_set)}")
    log()

    log("[capabilities]")
    for k, v in capability_map.items():
        log(f"  {k:<24} -> {v}")
    log()

    log("[action_presence]")
    for k, v in action_presence.items():
        log(f"  {k:<32} -> {v}")
    log()

    log("[smoke]")
    for name, result in smoke_results.items():
        log("  " + fmt_step_line(name, result))
    log()

    log("[summary]")
    log(f"  critical_capabilities_ok -> {critical_capabilities_ok}")
    log(f"  critical_actions_ok      -> {critical_actions_ok}")
    log(f"  critical_smoke_ok        -> {critical_smoke_ok}")

    if bootstrap_info is not None:
        log()
        log("[bootstrap_info]")
        log(f"  ok            -> {bootstrap_info.get('ok')}")
        log(f"  reason        -> {bootstrap_info.get('reason')}")
        log(f"  count_before  -> {bootstrap_info.get('count_before')}")
        log(f"  count_after   -> {bootstrap_info.get('count_after')}")

    log("================================================================================================")
    return 0 if overall == "BOOT_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
