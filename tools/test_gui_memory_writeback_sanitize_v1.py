#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


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
        self.snapshot_payload["snapshot"]["session_cache"]["active_session"]["recent_messages"] = list(self.recent_messages)

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

            if (not query) or (query in content) or ("回忆" in query) or ("刚才" in query) or ("我是谁" in query):
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

    def action_memory_append_action(self, action_name="", status="success", result_summary="", **kwargs):
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


class EchoAICore:
    def __init__(self, dispatcher: FakeMemoryDispatcher):
        self.dispatcher = dispatcher
        self.calls = []

    def _resolve_dispatcher(self):
        return self.dispatcher

    def ask(self, text, *args, **kwargs):
        text = str(text)
        self.calls.append(("ask", text))
        return {"reply": f"FAKE_AICORE_REPLY::{text}"}

    def chat(self, text, *args, **kwargs):
        text = str(text)
        self.calls.append(("chat", text))
        return {"reply": f"FAKE_AICORE_CHAT_REPLY::{text}"}


def main():
    parser = argparse.ArgumentParser(description="TEST GUI MEMORY WRITEBACK SANITIZE V1")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("TEST GUI MEMORY WRITEBACK SANITIZE V1")
    print("=" * 96)
    print(f"root     : {root}")
    print(f"gui_main : {gui_main}")

    mod = load_module_from_path("sanhua_gui_main_for_memory_sanitize_test_v1", gui_main)

    static_checks = {
        "sanitize_helper": hasattr(mod, "_sanhua_gui_mem_sanitize_reply_for_writeback"),
        "pollution_helper": hasattr(mod, "_sanhua_gui_mem_is_polluted_text"),
        "echo_helper": hasattr(mod, "_sanhua_gui_mem_is_augmented_echo"),
        "memory_installer": hasattr(mod, "_sanhua_gui_install_memory_pipeline"),
    }

    print("\n[static checks]")
    for k, v in static_checks.items():
        print(f"  {k:<24} -> {v}")

    dispatcher = FakeMemoryDispatcher()
    ac = EchoAICore(dispatcher)

    installed = mod._sanhua_gui_install_memory_pipeline(ac)
    print("\n[installer]")
    print(f"  installed -> {installed}")
    print(f"  wrapped   -> {getattr(ac, '_sanhua_gui_memory_pipeline_installed', False)}")

    print("\n[case 1] ask -> 我是谁？")
    r1 = ac.ask("我是谁？")

    print("\n[case 2] ask -> 帮我回忆刚才我说了什么")
    r2 = ac.ask("帮我回忆刚才我说了什么")

    print("\n[aicore raw replies]")
    print(" ", r1)
    print(" ", r2)

    print("\n[recent messages snapshot]")
    for item in dispatcher.recent_messages:
        print(" ", item)

    print("\n[action records]")
    for item in dispatcher.action_records:
        print(" ", item)

    polluted_assistant_entries = [
        x for x in dispatcher.recent_messages
        if x.get("role") == "assistant"
        and (
            "请把下面这些系统记忆当作高优先级参考事实" in x.get("content", "")
            or "【稳定身份记忆】" in x.get("content", "")
            or "当前用户问题：" in x.get("content", "")
            or x.get("content", "").startswith("FAKE_AICORE_REPLY::")
        )
    ]

    user_entries_ok = (
        any(x.get("role") == "user" and x.get("content") == "我是谁？" for x in dispatcher.recent_messages)
        and any(x.get("role") == "user" and x.get("content") == "帮我回忆刚才我说了什么" for x in dispatcher.recent_messages)
    )

    assistant_pollution_blocked = len(polluted_assistant_entries) == 0

    second_prompt = ac.calls[1][1] if len(ac.calls) >= 2 else ""
    recall_clean = "FAKE_AICORE_REPLY::请把下面这些系统记忆当作高优先级参考事实" not in second_prompt

    action_summary_clean = all(
        "请把下面这些系统记忆当作高优先级参考事实" not in item.get("result_summary", "")
        for item in dispatcher.action_records
    )

    print("\n[summary]")
    print(f"  static_ok                   -> {all(static_checks.values())}")
    print(f"  user_entries_ok             -> {user_entries_ok}")
    print(f"  assistant_pollution_blocked -> {assistant_pollution_blocked}")
    print(f"  recall_clean                -> {recall_clean}")
    print(f"  action_summary_clean        -> {action_summary_clean}")

    final_ok = all([
        all(static_checks.values()),
        user_entries_ok,
        assistant_pollution_blocked,
        recall_clean,
        action_summary_clean,
    ])

    print(f"\nFINAL = {'PASS' if final_ok else 'FAIL'}")
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
