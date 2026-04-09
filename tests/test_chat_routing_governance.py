from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.gui_bridge import chat_orchestrator as chat_mod
from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator


def _install_bridge_stubs(monkeypatch, *, local_ok=False, local_reply="LOCAL"):
    monkeypatch.setattr(chat_mod, "extract_text", lambda obj: obj)
    monkeypatch.setattr(chat_mod, "display_is_polluted", lambda text: False)
    monkeypatch.setattr(chat_mod, "append_chat", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_mod, "append_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_mod, "mem_execute", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        chat_mod,
        "try_local_memory_answer",
        lambda *_args, **_kwargs: {"ok": local_ok, "reply": local_reply, "kind": "memory"},
    )


class FakeAICore:
    def __init__(self, *, chat_result=None, chat_exc=None, ask_result=None, ask_exc=None):
        self.chat_result = chat_result
        self.chat_exc = chat_exc
        self.ask_result = ask_result
        self.ask_exc = ask_exc
        self.calls = []

    def chat(self, query):
        self.calls.append(f"chat:{query}")
        if self.chat_exc:
            raise self.chat_exc
        return self.chat_result

    def ask(self, query):
        self.calls.append(f"ask:{query}")
        if self.ask_exc:
            raise self.ask_exc
        return self.ask_result


def _make_orchestrator(monkeypatch, *, local_ok=False, action_plan=None, aicore=None):
    _install_bridge_stubs(monkeypatch, local_ok=local_ok)
    action_calls = []
    action_plan = action_plan or {}
    aicore = aicore or FakeAICore()
    logs = []

    def action_caller(name, payload):
        action_calls.append(name)
        outcome = action_plan.get(name, "")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    orch = GUIChatOrchestrator(
        ctx=SimpleNamespace(),
        aicore=aicore,
        action_caller=action_caller,
        list_actions=lambda: [],
        logger=logs.append,
        strip_protocol=lambda x: str(x or ""),
    )
    return orch, aicore, action_calls, logs


def test_local_memory_short_circuit_keeps_original_semantics(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=True,
        action_plan={"ai.chat": "AI", "aicore.chat": "LEGACY"},
        aicore=FakeAICore(chat_result="AICORE", ask_result="ASK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "LOCAL"
    assert action_calls == []
    assert aicore.calls == []
    assert any("⚡ chat short-circuit -> local memory" in line for line in logs)


def test_default_non_local_route_prefers_ai_chat(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK", "aicore.chat": "LEGACY"},
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "AI_OK"
    assert action_calls == ["ai.chat"]
    assert aicore.calls == []
    assert any("🤖 chat route -> ai.chat" in line for line in logs)
    assert not any("AICore.ask" in line for line in logs)


def test_ai_chat_failure_then_fallback_to_aicore_chat(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("boom")},
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "AICORE_OK"
    assert action_calls == ["ai.chat"]
    assert aicore.calls == ["chat:你好"]
    ai_idx = next(i for i, line in enumerate(logs) if "🤖 chat route -> ai.chat" in line)
    aicore_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.chat" in line)
    assert ai_idx < aicore_idx


def test_aicore_chat_failure_then_legacy_action_fallback(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("ai down"), "aicore.chat": "LEGACY_OK"},
        aicore=FakeAICore(chat_exc=RuntimeError("aicore down"), ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "LEGACY_OK"
    assert action_calls == ["ai.chat", "aicore.chat"]
    assert aicore.calls == ["chat:你好"]
    assert not any("AICore.ask [retained probe]" in line for line in logs)


def test_aicore_ask_is_retained_probe_not_default_first_hop(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("ai down"), "aicore.chat": RuntimeError("legacy down")},
        aicore=FakeAICore(chat_exc=RuntimeError("aicore down"), ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "ASK_OK"
    assert action_calls == ["ai.chat", "aicore.chat"]
    assert aicore.calls == ["chat:你好", "ask:你好"]
    ai_idx = next(i for i, line in enumerate(logs) if "🤖 chat route -> ai.chat" in line)
    chat_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.chat" in line)
    legacy_idx = next(i for i, line in enumerate(logs) if "🤖 chat route -> action:aicore.chat" in line)
    ask_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.ask [retained probe]" in line)
    assert ai_idx < chat_idx < legacy_idx < ask_idx


def test_gui_entry_source_delegates_chat_to_orchestrator():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")

    start = source.index("def _chat_via_actions(self, user_text: str) -> str:")
    end = source.index("\n    def _speak_if_enabled(self, text: str):", start)
    block = source[start:end]

    assert "from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator" in block
    assert "_orchestrator = GUIChatOrchestrator(" in block
    assert "return _orchestrator.handle_chat(user_text)" in block

    assert 'chat route -> ai.chat' not in block
    assert 'chat route -> AICore.chat' not in block
    assert 'chat route -> action:aicore.chat' not in block
    assert 'chat route -> AICore.ask [retained probe]' not in block
    assert "_try_local_memory" not in block
