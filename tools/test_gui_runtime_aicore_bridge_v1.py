#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
test_gui_runtime_aicore_bridge_v1.py

目标：
1. 静态检查 gui_main.py 是否已注入 runtime bridge
2. 动态导入 gui_main.py
3. 用 FakeRuntime + FakeAICore 验证 runtime.chat() 是否被桥接到 AICore.ask/chat
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


PATCH_BLOCK_START = "# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_START ==="
PATCH_BLOCK_END = "# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_END ==="
PATCH_CALL_MARKER = "SANHUA_GUI_RUNTIME_AICORE_BRIDGE_CALL"


def load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeAICore:
    def __init__(self):
        self.calls = []

    def ask(self, prompt: str, *args, **kwargs):
        self.calls.append(("ask", prompt, args, kwargs))
        return {
            "reply": f"FAKE_AICORE_REPLY::{prompt}"
        }


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def chat(self, text: str, *args, **kwargs):
        self.calls.append(("chatonly", text, args, kwargs))
        return f"CHATONLY::{text}"


def main() -> int:
    parser = argparse.ArgumentParser(description="测试 GUI runtime AICore bridge")
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("TEST GUI RUNTIME AICORE BRIDGE V1")
    print("=" * 96)
    print(f"root     : {root}")
    print(f"gui_main : {gui_main}")

    if not gui_main.exists():
        print("[ERROR] gui_main_not_found")
        return 2

    text = gui_main.read_text(encoding="utf-8")

    print("\n[static check]")
    static_checks = {
        PATCH_BLOCK_START: PATCH_BLOCK_START in text,
        PATCH_BLOCK_END: PATCH_BLOCK_END in text,
        PATCH_CALL_MARKER: PATCH_CALL_MARKER in text,
        "_sanhua_gui_install_runtime_aicore_bridge(": "_sanhua_gui_install_runtime_aicore_bridge(" in text,
    }
    for k, v in static_checks.items():
        print(f"  {k:<55} -> {v}")

    static_ok = all(static_checks.values())

    print("\n[import gui module]")
    mod = load_module_from_path("sanhua_gui_main_for_runtime_bridge_test_v1", gui_main)

    installer = getattr(mod, "_sanhua_gui_install_runtime_aicore_bridge", None)
    if not callable(installer):
        print("[ERROR] installer_not_found")
        return 3

    fake_runtime = FakeRuntime()
    fake_ac = FakeAICore()

    installed = installer(fake_runtime, fake_ac)
    print(f"[installer] installed -> {installed}")
    print(
        f"[installer] marker    -> "
        f"{getattr(fake_runtime, '_sanhua_gui_runtime_bridge_installed', False)}"
    )

    result = fake_runtime.chat("我是谁？")
    print("\n[dynamic case]")
    print(f"result            -> {result}")
    print(f"fake_runtime.calls -> {fake_runtime.calls}")
    print(f"fake_ac.calls      -> {fake_ac.calls}")

    route_ok = (
        len(fake_ac.calls) == 1
        and fake_ac.calls[0][0] == "ask"
        and fake_runtime.calls == []
    )

    print("\n[summary]")
    print(f"static_ok -> {static_ok}")
    print(f"route_ok  -> {route_ok}")

    final_ok = static_ok and route_ok
    print(f"\nFINAL = {'PASS' if final_ok else 'FAIL'}")
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
