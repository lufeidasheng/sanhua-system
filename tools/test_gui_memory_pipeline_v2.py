#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from pprint import pprint


def load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def get_aicore(root: Path):
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from core.aicore.aicore import get_aicore_instance

    aicore = get_aicore_instance()
    bootstrap_info = None
    if hasattr(aicore, "_bootstrap_action_registry"):
        bootstrap_info = aicore._bootstrap_action_registry(force=True)
    return aicore, bootstrap_info


def resolve_dispatcher(aicore):
    resolver = getattr(aicore, "_resolve_dispatcher", None)
    if callable(resolver):
        try:
            d = resolver()
            if d is not None:
                return d
        except Exception:
            pass

    for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
        d = getattr(aicore, name, None)
        if d is not None:
            return d

    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        return ACTION_MANAGER
    except Exception:
        return None


def dispatcher_has(dispatcher, name: str) -> bool:
    if dispatcher is None:
        return False

    getter = getattr(dispatcher, "get_action", None)
    if callable(getter):
        try:
            return getter(name) is not None
        except Exception:
            pass

    actions = getattr(dispatcher, "actions", None)
    if isinstance(actions, dict):
        return name in actions

    return False


def call_action_meta(dispatcher, name: str, **kwargs):
    if dispatcher is None:
        return {}

    getter = getattr(dispatcher, "get_action", None)
    if callable(getter):
        try:
            meta = getter(name)
        except Exception:
            meta = None
        if meta is not None:
            fn = getattr(meta, "func", None)
            if callable(fn):
                trials = [
                    lambda: fn(**kwargs),
                    lambda: fn(context={}, **kwargs),
                    lambda: fn(context=None, **kwargs),
                    lambda: fn(),
                ]
                last_error = None
                for trial in trials:
                    try:
                        result = trial()
                        return result if isinstance(result, dict) else {"result": result}
                    except TypeError as e:
                        last_error = e
                        continue
                    except Exception as e:
                        return {"ok": False, "error": str(e), "action": name}
                if last_error is not None:
                    return {"ok": False, "error": str(last_error), "action": name}

    for method_name in ("execute", "call_action"):
        fn = getattr(dispatcher, method_name, None)
        if not callable(fn):
            continue

        trials = (
            lambda: fn(name, **kwargs),
            lambda: fn(name, kwargs),
            lambda: fn(name),
        )
        last_error = None
        for trial in trials:
            try:
                result = trial()
                return result if isinstance(result, dict) else {"result": result}
            except TypeError as e:
                last_error = e
                continue
            except Exception as e:
                return {"ok": False, "error": str(e), "action": name}

        if last_error is not None:
            return {"ok": False, "error": str(last_error), "action": name}

    return {}


def recent_messages_from_snapshot(snapshot_result: dict) -> list[dict]:
    snap = (snapshot_result or {}).get("snapshot") or {}
    session = ((snap.get("session_cache") or {}).get("active_session") or {})
    recent = session.get("recent_messages") or []
    out = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if content:
            out.append({"role": role or "unknown", "content": content})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="测试 GUI memory pipeline v2")
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("TEST GUI MEMORY PIPELINE V2")
    print("=" * 96)
    print(f"root     : {root}")
    print(f"gui_main : {gui_main}")

    if not gui_main.exists():
        print("[ERROR] gui_main.py 不存在")
        return 2

    source = gui_main.read_text(encoding="utf-8")

    print("\n[static check]")
    static_needles = (
        "# === SANHUA_GUI_MEMORY_PIPELINE_V1_START ===",
        "# === SANHUA_GUI_MEMORY_PIPELINE_V1_END ===",
        "_sanhua_gui_install_memory_pipeline(",
        "_sanhua_gui_mem_get_action_meta(",
        "_sanhua_gui_mem_call_action_meta(",
    )
    static_ok = True
    for needle in static_needles:
        hit = needle in source
        print(f"  {needle:<60} -> {hit}")
        static_ok = static_ok and hit

    aicore, bootstrap_info = get_aicore(root)
    dispatcher = resolve_dispatcher(aicore)

    print("\n[bootstrap_info]")
    pprint(bootstrap_info)

    print("\n[action presence]")
    required_actions = [
        "memory.health",
        "memory.snapshot",
        "memory.search",
        "memory.recall",
        "memory.append_chat",
        "memory.append_action",
    ]
    actions_ok = True
    for name in required_actions:
        hit = dispatcher_has(dispatcher, name)
        print(f"  {name:<28} -> {hit}")
        actions_ok = actions_ok and hit

    print("\n[import gui module]")
    mod = load_module_from_path("sanhua_gui_main_for_memory_test_v2", gui_main)
    installer = getattr(mod, "_sanhua_gui_install_memory_pipeline", None)
    if not callable(installer):
        print("[ERROR] 未找到 _sanhua_gui_install_memory_pipeline")
        return 3

    captured_inputs: list[str] = []

    def probe_chat(user_input, *args, **kwargs):
        captured_inputs.append(str(user_input))
        return {"reply": f"probe-ok: {str(user_input)[:160]}"}

    setattr(aicore, "chat", probe_chat)
    installed = installer(aicore)

    print(f"\n[installer] installed -> {installed}")
    wrapped = getattr(aicore, "chat", None)
    print(f"[installer] wrapped    -> {getattr(wrapped, '_sanhua_gui_memory_wrapped', False)}")

    case_results = []

    # case 1: identity must include real identity memory, not empty placeholder
    captured_inputs.clear()
    result_1 = aicore.chat("我是谁？")
    prompt_1 = captured_inputs[-1] if captured_inputs else ""
    hit_identity = ("用户名：鹏" in prompt_1) or ("identity.name" in prompt_1 and "鹏" in prompt_1) or ("别名：" in prompt_1 and "鹏" in prompt_1)
    case_results.append(("case_identity_real", hit_identity, prompt_1[:1000], result_1))

    # case 2: write recent conversation then recall it
    marker = f"gui-memory-marker-{uuid.uuid4().hex[:8]}"
    captured_inputs.clear()
    _ = aicore.chat(f"请记住这句话：{marker}")
    _ = aicore.chat("帮我回忆刚才我说了什么")
    prompt_2 = captured_inputs[-1] if captured_inputs else ""
    hit_recent = marker in prompt_2
    case_results.append(("case_recent_recall", hit_recent, prompt_2[:1500], None))

    # case 3: snapshot should really contain the marker
    snap = call_action_meta(dispatcher, "memory.snapshot")
    recent = recent_messages_from_snapshot(snap)
    hit_snapshot = any(marker in x.get("content", "") for x in recent)
    case_results.append(("case_snapshot_writeback", hit_snapshot, recent[-8:], None))

    print("\n[cases]")
    all_ok = static_ok and actions_ok
    for name, ok, detail, result in case_results:
        print("-" * 96)
        print(f"{name}: {'PASS' if ok else 'FAIL'}")
        print("[detail]")
        if isinstance(detail, str):
            print(detail)
        else:
            print(json.dumps(detail, ensure_ascii=False, indent=2))
        if result is not None:
            print("[result]")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        all_ok = all_ok and ok

    print("\n[summary]")
    print(f"static_ok  -> {static_ok}")
    print(f"actions_ok -> {actions_ok}")
    for name, ok, _, _ in case_results:
        print(f"{name:<24} -> {ok}")

    final = "PASS" if all_ok else "FAIL"
    print(f"\nFINAL = {final}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
