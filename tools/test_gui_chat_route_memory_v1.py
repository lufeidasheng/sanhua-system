#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"load spec failed: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeActionMeta:
    def __init__(self, func):
        self.func = func


class FakeMemoryDispatcher:
    """
    给 GUI memory pipeline 提供假的 memory.* 动作
    """

    def __init__(self):
        self.recent_messages = [
            {"role": "user", "content": "记忆模块应该在哪里？"},
            {"role": "user", "content": "三花聚顶应该怎样做长期记忆压缩？"},
            {"role": "user", "content": "系统以后怎么记住我是鹏？"},
            {"role": "user", "content": "现在三花聚顶的记忆层应该怎么接入 AICore？"},
        ]
        self.action_records = []
        self.snapshot_payload = {
            "snapshot": {
                "persona": {
                    "user_profile": {
                        "name": "鹏",
                        "aliases": ["鹏", "鹏鹏"],
                        "notes": "用户为鹏；长期偏好务实、系统化、高信息密度、结论优先、避免空话。",
                        "project_focus": [
                            "AICore",
                            "MemoryManager",
                            "PromptMemoryBridge",
                            "三花聚顶",
                        ],
                        "stable_facts": {
                            "identity.name": "鹏",
                            "system.primary_project": "三花聚顶",
                            "response.preference": "务实、系统化、高信息密度、结论优先",
                            "memory_architecture_focus": "记忆层与其他 core 共存，并作为独立核心服务存在",
                        },
                    }
                },
                "session_cache": {
                    "active_session": {
                        "recent_messages": list(self.recent_messages)
                    }
                },
            }
        }

    def _sync_snapshot_recent(self):
        self.snapshot_payload["snapshot"]["session_cache"]["active_session"]["recent_messages"] = list(
            self.recent_messages
        )

    def _append_recent(self, role: str, content: str):
        role = str(role or "").strip() or "user"
        content = str(content or "").strip()
        if not content:
            return
        self.recent_messages.append({"role": role, "content": content})
        self.recent_messages = self.recent_messages[-12:]
        self._sync_snapshot_recent()

    def action_memory_snapshot(self, **kwargs):
        self._sync_snapshot_recent()
        return self.snapshot_payload

    def action_memory_recall(self, query="", limit=5, **kwargs):
        query = str(query or "").strip()
        limit = int(limit or 5)

        hits = []
        for item in reversed(self.recent_messages):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if not query or query in content or "回忆" in query or "刚才" in query or "我是谁" in query:
                hits.append({
                    "match_text": content,
                    "role": item.get("role", "unknown"),
                })
            if len(hits) >= limit:
                break

        hits.reverse()
        return {"results": hits}

    def action_memory_append_chat(self, role="user", content="", **kwargs):
        self._append_recent(role, content)
        return {"ok": True, "status": "ok"}

    def action_memory_append_action(
        self,
        action_name="",
        status="success",
        result_summary="",
        **kwargs,
    ):
        self.action_records.append({
            "action_name": str(action_name or "").strip(),
            "status": str(status or "").strip(),
            "result_summary": str(result_summary or "").strip(),
        })
        return {"ok": True, "status": "ok"}

    def get_action(self, action_name: str):
        mapping = {
            "memory.snapshot": self.action_memory_snapshot,
            "memory.recall": self.action_memory_recall,
            "memory.append_chat": self.action_memory_append_chat,
            "memory.append_action": self.action_memory_append_action,
        }
        fn = mapping.get(action_name)
        if fn is None:
            return None
        return FakeActionMeta(fn)

    def execute(self, action_name: str, *args, **kwargs):
        meta = self.get_action(action_name)
        if meta is None:
            raise RuntimeError(f"unknown action: {action_name}")
        return meta.func(**kwargs)

    def call_action(self, action_name: str, *args, **kwargs):
        return self.execute(action_name, *args, **kwargs)


class FakeAICore:
    def __init__(self, dispatcher: FakeMemoryDispatcher):
        self.dispatcher = dispatcher
        self.calls = []

    def _resolve_dispatcher(self):
        return self.dispatcher

    def ask(self, text, *args, **kwargs):
        text = str(text)
        self.calls.append(("ask", text, args, kwargs))
        return {"reply": f"FAKE_AICORE_REPLY::{text}"}

    def chat(self, text, *args, **kwargs):
        text = str(text)
        self.calls.append(("chat", text, args, kwargs))
        return {"reply": f"FAKE_AICORE_CHAT_REPLY::{text}"}


class FakeRouter:
    def __init__(self):
        self.calls = []

    def route(self, text: str):
        self.calls.append(text)
        return SimpleNamespace(
            kind="chat",
            action_name=None,
            action_params={},
            action_result=None,
            chain_steps=[{"stage": "route", "kind": "chat", "text": text}],
        )


class FakeChain:
    def __init__(self):
        self.calls = []

    def show_chain(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class FakeChatPanel:
    """
    兼容 gui_main 真实调用风格：
    add_bubble(text, is_user=False)
    """

    def __init__(self):
        self.bubbles = []

    def add_bubble(self, text: str, is_user: bool = False):
        self.bubbles.append((str(text), bool(is_user)))


class DummyMainWindow:
    pass


def bind_method(obj, owner_cls, name: str):
    fn = getattr(owner_cls, name)
    return fn.__get__(obj, obj.__class__)


def build_dummy_window(gui_mod):
    w = DummyMainWindow()

    w.logs = []
    w.actions_called = []

    def append_log(msg: str):
        w.logs.append(str(msg))

    def _strip_llm_protocol(text: str):
        return str(text or "").replace("<think>", "").replace("</think>", "").strip()

    def _fmt(obj):
        return str(obj)

    def _list_actions():
        return []

    def _safe_call_action(name, params=None):
        w.actions_called.append((name, params))
        raise RuntimeError(f"fake_action_disabled:{name}")

    w.append_log = append_log
    w._strip_llm_protocol = _strip_llm_protocol
    w._fmt = _fmt
    w._list_actions = _list_actions
    w._safe_call_action = _safe_call_action

    w.tts_enabled = False
    w.chat_panel = FakeChatPanel()
    w.chain = FakeChain()
    w.router = FakeRouter()

    dispatcher = FakeMemoryDispatcher()
    w.ac = FakeAICore(dispatcher)

    w._chat_via_actions = bind_method(w, gui_mod.MainWindow, "_chat_via_actions")
    w._speak_if_enabled = bind_method(w, gui_mod.MainWindow, "_speak_if_enabled")
    w.handle_user_message = bind_method(w, gui_mod.MainWindow, "handle_user_message")

    installed = False
    if hasattr(gui_mod, "_sanhua_gui_install_memory_pipeline"):
        installed = bool(gui_mod._sanhua_gui_install_memory_pipeline(w.ac))

    return w, dispatcher, installed


def main():
    parser = argparse.ArgumentParser(description="测试 GUI 聊天路由 + memory pipeline")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("TEST GUI CHAT ROUTE MEMORY V1")
    print("=" * 96)
    print(f"root     : {root}")
    print(f"gui_main : {gui_main}")

    mod = load_module_from_path("sanhua_gui_main_for_chat_route_test_v1", gui_main)

    static_checks = {
        "MainWindow._chat_via_actions": hasattr(mod.MainWindow, "_chat_via_actions"),
        "MainWindow.handle_user_message": hasattr(mod.MainWindow, "handle_user_message"),
        "MainWindow._speak_if_enabled": hasattr(mod.MainWindow, "_speak_if_enabled"),
        "memory_pipeline_helper": hasattr(mod, "_sanhua_gui_install_memory_pipeline"),
    }

    print("\n[static checks]")
    for k, v in static_checks.items():
        print(f"  {k:<36} -> {v}")

    win, dispatcher, installer_ok = build_dummy_window(mod)

    print("\n[installer]")
    print(f"  installed -> {installer_ok}")
    print(f"  wrapped   -> {getattr(win.ac, '_sanhua_gui_memory_pipeline_installed', False)}")

    print("\n[case 1] user = 我是谁？")
    win.handle_user_message("我是谁？")

    print("\n[case 2] user = 帮我回忆刚才我说了什么")
    win.handle_user_message("帮我回忆刚才我说了什么")

    ac_calls = list(win.ac.calls)

    print("\n[aicore calls]")
    for item in ac_calls:
        print(" ", item[:2])

    print("\n[action fallback calls]")
    for item in win.actions_called:
        print(" ", item)

    print("\n[router calls]")
    for item in win.router.calls:
        print(" ", item)

    print("\n[chat bubbles]")
    for item in win.chat_panel.bubbles:
        print(" ", item)

    print("\n[recent messages snapshot]")
    for item in dispatcher.recent_messages:
        print(" ", item)

    print("\n[logs]")
    for line in win.logs[-30:]:
        print(" ", line)

    call_1_text = ac_calls[0][1] if len(ac_calls) >= 1 else ""
    call_2_text = ac_calls[1][1] if len(ac_calls) >= 2 else ""

    case_identity = (
        "【稳定身份记忆】" in call_1_text
        and "用户名：鹏" in call_1_text
        and "当前用户问题：\n我是谁？" in call_1_text
    )

    case_recent_recall = (
        "【最近会话】" in call_2_text
        and "我是谁？" in call_2_text
        and "帮我回忆刚才我说了什么" in call_2_text
    )

    case_writeback = any(
        msg.get("role") == "assistant" and "FAKE_AICORE_REPLY::" in msg.get("content", "")
        for msg in dispatcher.recent_messages
    )

    route_ok = len(win.router.calls) == 2 and len(ac_calls) == 2

    # 真实 GUI add_bubble(text, is_user=False)
    ui_ok = any(
        isinstance(item, tuple)
        and len(item) >= 2
        and isinstance(item[0], str)
        and item[0].startswith("FAKE_AICORE_REPLY::")
        and item[1] is False
        for item in win.chat_panel.bubbles
    )

    print("\n[summary]")
    print(f"  static_ok         -> {all(static_checks.values())}")
    print(f"  installer_ok      -> {installer_ok}")
    print(f"  route_ok          -> {route_ok}")
    print(f"  ui_ok             -> {ui_ok}")
    print(f"  case_identity     -> {case_identity}")
    print(f"  case_recent_recall-> {case_recent_recall}")
    print(f"  case_writeback    -> {case_writeback}")

    final_ok = all([
        all(static_checks.values()),
        installer_ok,
        route_ok,
        ui_ok,
        case_identity,
        case_recent_recall,
        case_writeback,
    ])

    print(f"\nFINAL = {'PASS' if final_ok else 'FAIL'}")
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
