#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")

    mod = importlib.util.module_from_spec(spec)

    # 关键修复：
    # dataclass / typing / forward refs 在 exec_module 期间可能会访问 sys.modules[__module__]
    # 如果这里不预注册，就会出现 NoneType.__dict__ 报错
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        # 失败时回滚，避免污染 sys.modules
        if sys.modules.get(module_name) is mod:
            del sys.modules[module_name]
        raise


class FakeActionMeta:
    def __init__(self, func):
        self.func = func


class FakeMemoryDispatcher:
    def __init__(self, state):
        self.state = state
        self.actions = {
            "memory.snapshot": FakeActionMeta(self.action_memory_snapshot),
            "memory.recall": FakeActionMeta(self.action_memory_recall),
            "memory.append_chat": FakeActionMeta(self.action_memory_append_chat),
            "memory.append_action": FakeActionMeta(self.action_memory_append_action),
        }

    def get_action(self, name):
        return self.actions.get(name)

    def action_memory_snapshot(self, **kwargs):
        return {
            "ok": True,
            "snapshot": {
                "persona": {
                    "user_profile": self.state["persona"],
                },
                "session_cache": {
                    "active_session": {
                        "recent_messages": list(self.state["recent_messages"]),
                    }
                },
            },
        }

    def action_memory_recall(self, query=None, limit=5, **kwargs):
        query = str(query or "").strip()
        limit = int(limit or 5)
        hits = []

        for item in self.state["recent_messages"]:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if query and (query in content or any(tok in content for tok in query.split())):
                hits.append({
                    "match_text": content,
                    "content": {"content": content},
                })

        if not hits:
            for item in self.state["recent_messages"][-limit:]:
                content = str(item.get("content") or "").strip()
                if content:
                    hits.append({
                        "match_text": content,
                        "content": {"content": content},
                    })

        return {"ok": True, "results": hits[-limit:]}

    def action_memory_append_chat(self, role=None, content=None, **kwargs):
        role = str(role or "").strip() or "user"
        content = str(content or "").strip()
        if content:
            self.state["recent_messages"].append({"role": role, "content": content})
            self.state["recent_messages"] = self.state["recent_messages"][-8:]
        return {"ok": True}

    def action_memory_append_action(self, action_name=None, status=None, result_summary=None, **kwargs):
        self.state["action_records"].append({
            "action_name": str(action_name or "").strip(),
            "status": str(status or "").strip(),
            "result_summary": str(result_summary or "").strip(),
        })
        self.state["action_records"] = self.state["action_records"][-8:]
        return {"ok": True}


class FakeAICore:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.calls = []

    def ask(self, text, *args, **kwargs):
        self.calls.append(("ask", text, args, kwargs))
        return {"reply": f"FAKE_AICORE_REPLY::{text}"}

    def chat(self, text, *args, **kwargs):
        self.calls.append(("chat", text, args, kwargs))
        return {"reply": f"FAKE_AICORE_REPLY::{text}"}


class DummyWindow:
    def __init__(self, mod, ac):
        self.mod = mod
        self.ac = ac
        self.logs = []
        self.tts_enabled = False

    def append_log(self, msg):
        self.logs.append(str(msg))

    def _strip_llm_protocol(self, text):
        return str(text or "").strip()

    def _safe_call_action(self, action_name, payload):
        self.logs.append(f"[ACTION_FALLBACK] {action_name} {payload}")
        return {}

    def _list_actions(self):
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("TEST GUI DISPLAY SANITIZE LOCAL MEMORY FALLBACK V1")
    print("=" * 96)
    print(f"root     : {root}")
    print(f"gui_main : {gui_main}")

    if not gui_main.exists():
        print("[ERROR] gui_main not found")
        return 2

    text = gui_main.read_text(encoding="utf-8")

    static_checks = {
        "display_polluted_helper": "_sanhua_gui_display_is_polluted(" in text,
        "local_memory_answer_helper": "_sanhua_gui_try_local_memory_answer(" in text,
        "chat_route_method": "def _chat_via_actions(self, user_text: str) -> str:" in text,
        "polluted_log": "GUI display sanitize -> polluted AICore reply blocked" in text,
    }

    print("\n[static checks]")
    for k, v in static_checks.items():
        print(f"  {k:<30} -> {v}")

    mod = load_module_from_path("sanhua_gui_main_display_sanitize_test_v1", gui_main)

    state = {
        "persona": {
            "name": "鹏",
            "aliases": ["鹏", "鹏鹏"],
            "notes": "用户为鹏；长期偏好务实、系统化、高信息密度、结论优先、避免空话。",
            "project_focus": ["AICore", "MemoryManager", "PromptMemoryBridge", "三花聚顶"],
            "stable_facts": {
                "identity.name": "鹏",
                "system.primary_project": "三花聚顶",
                "response.preference": "务实、系统化、高信息密度、结论优先",
            },
        },
        "recent_messages": [
            {"role": "user", "content": "记忆模块应该在哪里？"},
            {"role": "user", "content": "三花聚顶应该怎样做长期记忆压缩？"},
            {"role": "user", "content": "系统以后怎么记住我是鹏？"},
            {"role": "user", "content": "现在三花聚顶的记忆层应该怎么接入 AICore？"},
        ],
        "action_records": [],
    }

    dispatcher = FakeMemoryDispatcher(state)
    ac = FakeAICore(dispatcher)

    installed = mod._sanhua_gui_install_memory_pipeline(ac)
    wrapped = bool(getattr(ac.ask, "_sanhua_gui_memory_wrapped", False))

    print("\n[installer]")
    print(f"  installed -> {installed}")
    print(f"  wrapped   -> {wrapped}")

    win = DummyWindow(mod, ac)

    print("\n[case 1] user = 我是谁？")
    reply_1 = mod.MainWindow._chat_via_actions(win, "我是谁？")

    print("\n[case 2] user = 帮我回忆刚才我说了什么")
    reply_2 = mod.MainWindow._chat_via_actions(win, "帮我回忆刚才我说了什么")

    print("\n[replies]")
    print("reply_1 ->")
    print(reply_1)
    print("reply_2 ->")
    print(reply_2)

    print("\n[aicore calls]")
    for item in ac.calls:
        print(f"  {item[0]} -> {item[1][:180]}")

    print("\n[recent messages snapshot]")
    for item in state["recent_messages"]:
        print(f"  {item}")

    print("\n[action records]")
    for item in state["action_records"]:
        print(f"  {item}")

    print("\n[logs]")
    for item in win.logs:
        print(f"  {item}")

    polluted_markers = (
        "请把下面这些系统记忆当作高优先级参考事实",
        "【稳定身份记忆】",
        "【最近会话】",
        "【相关记忆命中】",
        "当前用户问题：",
        "FAKE_AICORE_REPLY::",
    )

    reply_1_clean = all(m not in reply_1 for m in polluted_markers)
    reply_2_clean = all(m not in reply_2 for m in polluted_markers)

    assistant_entries = [x for x in state["recent_messages"] if x.get("role") == "assistant"]
    assistant_clean = True
    for x in assistant_entries:
        content = str(x.get("content") or "")
        if any(m in content for m in polluted_markers):
            assistant_clean = False
            break

    action_summary_clean = True
    for x in state["action_records"]:
        summary = str(x.get("result_summary") or "")
        if any(m in summary for m in polluted_markers):
            action_summary_clean = False
            break

    summary = {
        "static_ok": all(static_checks.values()),
        "installer_ok": bool(installed and wrapped),
        "reply_1_clean": reply_1_clean,
        "reply_2_clean": reply_2_clean,
        "assistant_clean": assistant_clean,
        "action_summary_clean": action_summary_clean,
        "identity_answer_ok": ("你是鹏" in reply_1) or ("你是" in reply_1 and "鹏" in reply_1),
        "recent_answer_ok": "你刚才说过" in reply_2,
    }

    print("\n[summary]")
    for k, v in summary.items():
        print(f"  {k:<24} -> {v}")

    final_ok = all(summary.values())
    print(f"\nFINAL = {'PASS' if final_ok else 'FAIL'}")
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
