from pathlib import Path
from dataclasses import dataclass
import inspect
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.gui_bridge import chat_orchestrator as chat_mod
from core.gui_bridge.chat_orchestrator import GUIChatOrchestrator


INTERNAL_ACTION_NAME_RE = re.compile(r"\b[a-z_]+\.[a-z_]+\b")
INTERNAL_STATUS_TERMS = (
    "【运行态真相摘要】",
    "当前 base_url",
    "当前模型路径",
    "AICore",
    "MemoryManager",
    "runtime_model_truth",
    "backend_status",
)


RUNTIME_STATUS = {
    "runtime_model_truth": {
        "ok": True,
        "runtime_model": "qwen3-8b-runtime",
        "model_path": "/models/qwen3-8b.gguf",
        "base_url": "http://127.0.0.1:8080/v1",
    },
    "backend_status": {
        "llamacpp": {
            "is_active": True,
            "config": {"type": "llamacpp_server", "model_name": "config-model"},
            "backend_info": {
                "type": "llamacpp_server",
                "model_name": "backend-model",
                "base_url": "http://127.0.0.1:8080/v1",
            },
        }
    },
}


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
    def __init__(
        self,
        *,
        chat_result=None,
        chat_exc=None,
        ask_result=None,
        ask_exc=None,
        memory_payload_builder=None,
        status=None,
    ):
        self.chat_result = chat_result
        self.chat_exc = chat_exc
        self.ask_result = ask_result
        self.ask_exc = ask_exc
        self.memory_payload_builder = memory_payload_builder
        self.status = status or {}
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

    def build_memory_payload(self, user_input, **kwargs):
        self.calls.append(f"memory_payload:{user_input}")
        if callable(self.memory_payload_builder):
            return self.memory_payload_builder(user_input, **kwargs)
        return {"final_prompt": user_input}

    def get_status(self):
        self.calls.append("get_status")
        return self.status


def _make_orchestrator(
    monkeypatch,
    *,
    local_ok=False,
    local_reply="LOCAL",
    action_plan=None,
    aicore=None,
    actions=None,
    action_payloads=None,
):
    _install_bridge_stubs(monkeypatch, local_ok=local_ok, local_reply=local_reply)
    action_calls = []
    action_plan = action_plan or {}
    aicore = aicore or FakeAICore()
    logs = []

    def action_caller(name, payload):
        action_calls.append(name)
        if action_payloads is not None:
            action_payloads.append((name, payload))
        outcome = action_plan.get(name, "")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    orch = GUIChatOrchestrator(
        ctx=SimpleNamespace(),
        aicore=aicore,
        action_caller=action_caller,
        list_actions=lambda: list(actions or []),
        logger=logs.append,
        strip_protocol=lambda x: str(x or ""),
    )
    return orch, aicore, action_calls, logs


def _trace_logs(logs):
    return [line for line in logs if line.startswith("TRACE chat ")]


def _load_gui_action_router_classes():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")
    start = source.index("@dataclass\nclass RoutedResult:")
    end = source.index("\ndef _action_name_in_list", start)
    namespace = {
        "Any": Any,
        "Callable": Callable,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "IntentRecognizer": None,
        "ActionSynthesizer": None,
        "dataclass": dataclass,
        "re": re,
    }
    exec(source[start:end], namespace)
    return namespace["ActionRouter"], namespace["RoutedResult"]


class _MatchCountingDispatcher:
    def __init__(self):
        self.match_calls = []

    def match_action(self, text):
        self.match_calls.append(text)
        return ("demo.action", {"text": text})


@pytest.mark.parametrize("text", ["晚上好", "当前模型是什么", "当前有哪些能力"])
def test_gui_action_router_chat_only_does_not_probe_actions_when_auto_action_off(text):
    ActionRouter, _ = _load_gui_action_router_classes()
    dispatcher = _MatchCountingDispatcher()
    router = ActionRouter(
        call_action=lambda *_args, **_kwargs: None,
        list_actions=lambda: [{"name": "demo.action"}],
        dispatcher_obj=dispatcher,
        log=lambda *_args, **_kwargs: None,
    )
    router.set_auto_action(False)

    result = router.route(text)

    assert result.kind == "chat"
    assert result.chain_steps == ["User", "ChatOnly"]
    assert dispatcher.match_calls == []


@pytest.mark.parametrize("text", ["/打开系统检测", "!打开系统检测"])
def test_gui_action_router_explicit_prefix_still_enters_action_chain(text):
    ActionRouter, _ = _load_gui_action_router_classes()
    dispatcher = _MatchCountingDispatcher()
    router = ActionRouter(
        call_action=lambda *_args, **_kwargs: None,
        list_actions=lambda: [{"name": "demo.action"}],
        dispatcher_obj=dispatcher,
        log=lambda *_args, **_kwargs: None,
    )
    router.set_auto_action(False)

    result = router.route(text)

    assert result.kind == "action"
    assert result.action_name == "demo.action"
    assert dispatcher.match_calls == ["打开系统检测"]


def test_gui_action_router_auto_action_still_allows_action_probe():
    ActionRouter, _ = _load_gui_action_router_classes()
    dispatcher = _MatchCountingDispatcher()
    router = ActionRouter(
        call_action=lambda *_args, **_kwargs: None,
        list_actions=lambda: [{"name": "demo.action"}],
        dispatcher_obj=dispatcher,
        log=lambda *_args, **_kwargs: None,
    )
    router.set_auto_action(True)

    result = router.route("当前有哪些能力")

    assert result.kind == "action"
    assert result.action_name == "demo.action"
    assert dispatcher.match_calls == ["当前有哪些能力"]


def test_gui_action_router_chat_only_branch_has_no_alias_probe():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")
    start = source.index("        # 2) 非显式：默认不执行动作（除非 auto_action_enabled）")
    end = source.index("        # 3) auto_action=True：alias → intent → chat", start)
    block = source[start:end]

    assert "if not self.auto_action_enabled:" in block
    assert "_match_alias" not in block
    assert "match_action" not in block
    assert 'RoutedResult(kind="chat"' in block


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
    assert any(
        "route=local_memory" in line
        and "source=memory.local" in line
        and "short_circuit=true" in line
        and "writeback=local_memory" in line
        for line in _trace_logs(logs)
    )


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
    assert aicore.calls == ["memory_payload:你好", "get_status"]
    assert any("🤖 chat route -> ai.chat" in line for line in logs)
    assert not any("AICore.ask" in line for line in logs)
    assert any(
        "route=ai.chat" in line
        and "source=ai.chat" in line
        and "short_circuit=false" in line
        and "display_boundary=false" in line
        and "writeback=sanitize_reply_for_writeback" in line
        for line in _trace_logs(logs)
    )


def test_chat_route_governance_boundary_is_centralized():
    source = inspect.getsource(chat_mod._classify_chat_route)
    handle_source = inspect.getsource(GUIChatOrchestrator.handle_chat)

    assert hasattr(chat_mod, "_classify_chat_route")
    assert "sysmon.status" in source
    assert "runtime.model_truth" in source
    assert "system.health_check" in source
    assert '"route": "ai.chat"' in source
    assert "route_decision = _classify_chat_route(q)" in handle_source


@pytest.mark.parametrize("question", ["晚上好"])
def test_route_governance_normal_chat_goes_to_ai_chat(monkeypatch, question):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat(question)

    assert reply == "AI_OK"
    assert action_calls == ["ai.chat"]
    assert any(
        "route=ai.chat" in line
        and "source=ai.chat" in line
        and "short_circuit=false" in line
        for line in _trace_logs(logs)
    )


@pytest.mark.parametrize("question", ["系统监控状态", "监控状态怎么样", "sysmon 状态"])
def test_route_governance_sysmon_questions_short_circuit(monkeypatch, question):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"sysmon.status": {"status": "OK"}},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat(question)

    assert reply == "系统监控状态：OK"
    assert action_calls == ["sysmon.status"]
    assert aicore.calls == []
    assert any(
        "route=sysmon.status" in line
        and "source=sysmon.status" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )
    assert not any("route=ai.chat" in line for line in _trace_logs(logs))
    assert not any("route=system.health_check" in line for line in _trace_logs(logs))


def test_route_governance_sysmon_unavailable_is_controlled_short_circuit(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"sysmon.status": RuntimeError("missing"), "ai.chat": "AI_OK"},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat("系统监控状态")

    assert "系统监控状态暂不可用" in reply
    assert action_calls == ["sysmon.status"]
    assert aicore.calls == []
    assert any(
        "route=sysmon.status.unavailable" in line
        and "source=sysmon.status.unavailable" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )
    assert not any("route=ai.chat" in line for line in _trace_logs(logs))


@pytest.mark.parametrize(
    "question",
    ["打开系统检测", "系统状态怎么样", "哪些模块异常", "建议优先处理什么", "怎么处理", "健康检查"],
)
def test_state_boundary_health_questions_only_call_health(monkeypatch, question):
    health = {
        "health": "DEGRADED",
        "modules": {
            "core": {"status": "OK"},
            "tts": {"status": "ERROR"},
        },
    }
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={
            "system.health_check": health,
            "sysmon.status": {"status": "OK"},
            "ai.chat": "AI_OK",
        },
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat(question)

    assert "系统健康：DEGRADED" in reply
    assert action_calls == ["system.health_check"]
    assert aicore.calls == []
    assert any(
        "route=system.health_check" in line
        and "source=system.health_check" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )
    assert not any("route=sysmon.status" in line for line in _trace_logs(logs))
    assert not any("route=ai.chat" in line for line in _trace_logs(logs))


@pytest.mark.parametrize("question", ["系统监控状态", "监控状态怎么样", "sysmon 状态"])
def test_state_boundary_sysmon_questions_only_call_sysmon(monkeypatch, question):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={
            "system.health_check": {"health": "OK", "modules": {}},
            "sysmon.status": {"status": "OK"},
            "ai.chat": "AI_OK",
        },
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat(question)

    assert reply == "系统监控状态：OK"
    assert action_calls == ["sysmon.status"]
    assert aicore.calls == []
    assert any(
        "route=sysmon.status" in line
        and "source=sysmon.status" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )
    assert not any("route=system.health_check" in line for line in _trace_logs(logs))
    assert not any("route=ai.chat" in line for line in _trace_logs(logs))


def test_ai_chat_payload_injects_memory_prompt_before_model(monkeypatch):
    payloads = []

    def memory_payload(user_input, **_kwargs):
        return {
            "final_prompt": (
                "【用户真相摘要】\n"
                "- 用户核心项目：三花聚顶\n\n"
                f"用户问题：\n{user_input}"
            )
        }

    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(
            chat_result="AICORE_OK",
            ask_result="ASK_OK",
            memory_payload_builder=memory_payload,
            status=RUNTIME_STATUS,
        ),
        action_payloads=payloads,
    )

    reply = orch.handle_chat("继续说")

    assert reply == "AI_OK"
    assert action_calls == ["ai.chat"]
    assert aicore.calls == ["memory_payload:继续说", "get_status"]
    assert len(payloads) == 1
    name, payload = payloads[0]
    assert name == "ai.chat"
    assert payload["query"] == "继续说"
    assert "【用户真相摘要】" in payload["prompt"]
    assert "三花聚顶" in payload["prompt"]
    assert "【运行态真相摘要】" in payload["prompt"]
    assert "运行态探测：可用" in payload["prompt"]
    assert "当前后端名：llamacpp" in payload["prompt"]
    assert "当前运行时模型名：qwen3-8b-runtime" in payload["prompt"]
    assert "当前模型路径：/models/qwen3-8b.gguf" in payload["prompt"]
    assert "当前 base_url：http://127.0.0.1:8080/v1" in payload["prompt"]
    assert payload["prompt"] == payload["text"] == payload["message"]
    assert payload["query"] != payload["prompt"]
    assert not any(call.startswith("chat:") or call.startswith("ask:") for call in aicore.calls)
    assert any("chat route -> ai.chat" in line for line in logs)


def test_ai_chat_context_builder_keeps_query_raw_and_prompt_enriched(monkeypatch):
    def memory_payload(user_input, **_kwargs):
        return {
            "final_prompt": (
                "【用户真相摘要】\n"
                "- 用户核心项目：三花聚顶\n\n"
                f"用户问题：\n{user_input}"
            )
        }

    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(
            chat_result="AICORE_OK",
            ask_result="ASK_OK",
            memory_payload_builder=memory_payload,
            status=RUNTIME_STATUS,
        ),
    )

    context = orch.ai_chat_context_builder.build("继续说", "系统提示")

    assert context["query"] == "继续说"
    assert context["system_prompt"] == "系统提示"
    assert context["system"] == "系统提示"
    assert context["prompt"] == context["text"] == context["message"]
    assert "【用户真相摘要】" in context["prompt"]
    assert "三花聚顶" in context["prompt"]
    assert "【运行态真相摘要】" in context["prompt"]
    assert "当前后端名：llamacpp" in context["prompt"]
    assert "当前运行时模型名：qwen3-8b-runtime" in context["prompt"]
    assert "当前模型路径：/models/qwen3-8b.gguf" in context["prompt"]
    assert action_calls == []
    assert aicore.calls == ["memory_payload:继续说", "get_status"]
    assert logs == []


def test_ai_chat_context_building_is_behind_single_builder_boundary():
    handle_source = inspect.getsource(GUIChatOrchestrator.handle_chat)

    assert hasattr(chat_mod, "AIChatContextBuilder")
    assert not hasattr(GUIChatOrchestrator, "_build_memory_truth_prompt")
    assert not hasattr(GUIChatOrchestrator, "_get_runtime_status_for_context")
    assert not hasattr(GUIChatOrchestrator, "_build_ai_chat_prompt")
    assert not hasattr(GUIChatOrchestrator, "_build_ai_chat_context")
    assert "ai_chat_context_builder.build" in handle_source
    assert "_build_memory_truth_prompt" not in handle_source
    assert "_get_runtime_status_for_context" not in handle_source
    assert "_build_ai_chat_prompt" not in handle_source


def test_runtime_truth_consumers_share_single_normalized_view(monkeypatch):
    calls = []

    def fake_view(status):
        calls.append(status)
        return {
            "__runtime_truth_view__": True,
            "probe_available": True,
            "model_name": "view-model",
            "model_source": "view-source",
            "backend_label": "view-backend",
            "backend_source": "view-backend-source",
            "model_path": "/view/model.gguf",
            "path_source": "view-path-source",
            "base_url": "http://view.local/v1",
            "base_url_source": "view-url-source",
        }

    monkeypatch.setattr(chat_mod, "_runtime_truth_view", fake_view)
    status = {"runtime_model_truth": {"runtime_model": "raw-model"}}

    reply = chat_mod._runtime_model_truth_reply("model", status)
    context = chat_mod._build_runtime_truth_context(status)

    assert calls == [status, status]
    assert "模型名：view-model（view-source）" in reply
    assert "后端名：view-backend（view-backend-source）" in reply
    assert "模型路径：/view/model.gguf（view-path-source）" in reply
    assert "当前后端名：view-backend（view-backend-source）" in context
    assert "当前运行时模型名：view-model（view-source）" in context
    assert "当前模型路径：/view/model.gguf（view-path-source）" in context
    assert "当前 base_url：http://view.local/v1（view-url-source）" in context


def test_runtime_truth_parsing_is_concentrated_in_single_view():
    view_source = inspect.getsource(chat_mod._runtime_truth_view)
    reply_source = inspect.getsource(chat_mod._runtime_model_truth_reply).split("\n", 1)[1]
    context_source = inspect.getsource(chat_mod._build_runtime_truth_context).split("\n", 1)[1]

    for token in ("runtime_model_truth", "backend_status", "SANHUA_MODEL", "SANHUA_LLAMA_BASE_URL"):
        assert token in view_source
        assert token not in reply_source
        assert token not in context_source

    assert "_runtime_truth_view(status)" in reply_source
    assert "_runtime_truth_view(status)" in context_source


def test_runtime_truth_view_empty_status_uses_explicit_degraded_values(monkeypatch):
    monkeypatch.delenv("SANHUA_MODEL", raising=False)
    monkeypatch.delenv("SANHUA_MODEL_PATH", raising=False)
    monkeypatch.delenv("SANHUA_ACTIVE_MODEL", raising=False)
    monkeypatch.delenv("SANHUA_MODEL_NAME", raising=False)
    monkeypatch.delenv("SANHUA_BACKEND_TYPE", raising=False)
    monkeypatch.delenv("SANHUA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("AICORE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("SANHUA_LLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    view = chat_mod._runtime_truth_view({})
    context = chat_mod._build_runtime_truth_context({})

    assert view["probe_available"] is False
    assert view["model_name"] == ""
    assert view["backend_label"] == ""
    assert view["model_path"] == ""
    assert view["base_url"] == ""
    assert "运行态探测：不可用" in context
    assert "当前运行时模型名：未知（配置值（运行态探测不可用））" in context
    assert "降级说明" in context


def test_followup_ai_chat_payload_still_injects_memory_prompt(monkeypatch):
    payloads = []

    def memory_payload(user_input, **_kwargs):
        return {
            "final_prompt": (
                "【用户真相摘要】\n"
                "- 用户偏好：持续上下文\n\n"
                f"用户问题：\n{user_input}"
            )
        }

    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(
            chat_result="AICORE_OK",
            ask_result="ASK_OK",
            memory_payload_builder=memory_payload,
            status=RUNTIME_STATUS,
        ),
        action_payloads=payloads,
    )

    first = orch.handle_chat("第一轮普通问题")
    second = orch.handle_chat("那这个继续说")

    assert first == "AI_OK"
    assert second == "AI_OK"
    assert action_calls == ["ai.chat", "ai.chat"]
    assert aicore.calls == [
        "memory_payload:第一轮普通问题",
        "get_status",
        "memory_payload:那这个继续说",
        "get_status",
    ]
    assert len(payloads) == 2
    assert payloads[0][1]["query"] == "第一轮普通问题"
    assert payloads[1][1]["query"] == "那这个继续说"
    assert "【用户真相摘要】" in payloads[0][1]["prompt"]
    assert "【用户真相摘要】" in payloads[1][1]["prompt"]
    assert "【运行态真相摘要】" in payloads[0][1]["prompt"]
    assert "【运行态真相摘要】" in payloads[1][1]["prompt"]
    assert "持续上下文" in payloads[1][1]["prompt"]
    assert "qwen3-8b-runtime" in payloads[1][1]["prompt"]
    assert "http://127.0.0.1:8080/v1" in payloads[1][1]["prompt"]
    assert all(name == "ai.chat" for name, _payload in payloads)
    assert not any(call.startswith("chat:") or call.startswith("ask:") for call in aicore.calls)
    assert sum("chat route -> ai.chat" in line for line in logs) == 2


def test_normal_greeting_hides_internal_status_from_ai_reply(monkeypatch):
    leaked_reply = (
        "晚上好。【运行态真相摘要】当前模型路径：/models/qwen3-8b.gguf，"
        "当前 base_url：http://127.0.0.1:8080/v1，AICore / MemoryManager 已接入。"
    )
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": leaked_reply},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat("晚上好")

    assert action_calls == ["ai.chat"]
    assert "普通对话" in reply
    assert "状态诊断" in reply
    assert not any(term in reply for term in INTERNAL_STATUS_TERMS)
    assert any("display boundary" in line for line in logs)
    assert any(
        "route=ai.chat" in line
        and "source=ai.chat" in line
        and "short_circuit=false" in line
        and "display_boundary=true" in line
        and "writeback=sanitize_reply_for_writeback" in line
        for line in _trace_logs(logs)
    )


def test_normal_task_hides_internal_status_from_ai_reply_and_writeback(monkeypatch):
    writes = []
    leaked_reply = (
        "我来帮你整理计划。runtime_model_truth 已加载，backend_status 正常，"
        "AICore 和 MemoryManager 链路可用。"
    )
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": leaked_reply},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )
    monkeypatch.setattr(chat_mod, "sanitize_reply_for_writeback", lambda _u, _p, obj: str(obj or ""))
    monkeypatch.setattr(chat_mod, "append_chat", lambda _ac, role, content: writes.append((role, content)))
    monkeypatch.setattr(chat_mod, "append_action", lambda _ac, name, status, detail: writes.append((name, status, detail)))

    reply = orch.handle_chat("帮我整理一下今天的计划")

    assert action_calls == ["ai.chat"]
    assert not any(term in reply for term in INTERNAL_STATUS_TERMS)
    assert writes
    assert not any(any(term in str(item) for term in INTERNAL_STATUS_TERMS) for item in writes)
    assert any("display boundary" in line for line in logs)


def test_diagnostic_context_allows_internal_status_from_ai_reply(monkeypatch):
    diagnostic_reply = (
        "诊断信息：当前模型路径：/models/qwen3-8b.gguf；"
        "当前 base_url：http://127.0.0.1:8080/v1；AICore / MemoryManager 链路可用。"
    )
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": diagnostic_reply},
        aicore=FakeAICore(status=RUNTIME_STATUS),
    )

    reply = orch.handle_chat("请给我诊断运行态")

    assert reply == diagnostic_reply
    assert action_calls == ["ai.chat"]
    assert "当前模型路径：/models/qwen3-8b.gguf" in reply
    assert "AICore" in reply
    assert not any("display boundary" in line for line in logs)


@pytest.mark.parametrize(
    ("question", "expected_focus"),
    [
        ("当前模型是什么", "模型名：qwen3-8b-runtime"),
        ("当前后端是什么", "后端名：env_backend"),
        ("当前模型路径是什么", "模型路径：/models/qwen3-8b.gguf"),
    ],
)
def test_runtime_truth_questions_short_circuit_before_ai_chat(monkeypatch, question, expected_focus):
    status = {
        "runtime_model_truth": {
            "ok": True,
            "runtime_model": "qwen3-8b-runtime",
            "model_path": "/models/qwen3-8b.gguf",
        },
        "backend_status": {
            "env_backend": {
                "is_active": True,
                "config": {"type": "llamacpp_server", "model_name": "config-model"},
                "backend_info": {"type": "llamacpp_server", "model_name": "backend-model"},
            }
        },
    }
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK", status=status),
    )

    reply = orch.handle_chat(question)

    assert expected_focus in reply
    assert "模型名：qwen3-8b-runtime" in reply
    assert "后端名：env_backend" in reply
    assert "模型路径：/models/qwen3-8b.gguf" in reply
    assert "AICore" not in reply
    assert action_calls == []
    assert aicore.calls == ["get_status"]
    assert any("runtime.model_truth" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)
    assert any(
        "route=runtime.model_truth" in line
        and "source=aicore.get_status" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )


def test_user_identity_question_still_uses_local_memory(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=True,
        local_reply="你是用户本人。",
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("我是谁")

    assert reply == "你是用户本人。"
    assert action_calls == []
    assert aicore.calls == []
    assert any("local memory" in line for line in logs)


def test_assistant_identity_question_short_circuits_before_ai_chat(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你是谁")

    assert "三花聚顶" in reply
    assert "聚核助手" in reply
    assert action_calls == []
    assert aicore.calls == []
    assert any("assistant.identity" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)


def test_capability_question_short_circuits_with_action_summary(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        actions=[{"name": "system.health_check"}, {"name": "memory.recall"}, {"name": "ai.chat"}],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你可以做什么")

    assert "本地数字中控助手" in reply
    assert "系统检测" in reply
    assert "记忆辅助" in reply
    assert "本地能力转接" in reply
    assert "当前系统已接入多项可用能力" in reply
    assert not INTERNAL_ACTION_NAME_RE.search(reply)
    assert action_calls == []
    assert aicore.calls == []
    assert any("system.capabilities" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)


def test_capability_reply_uses_single_entry_summary_builder(monkeypatch):
    seen = []

    class FakeCapabilityBuilder:
        def __init__(self, actions):
            seen.append(actions)

        def build(self):
            return "CAPABILITY_BUILDER_REPLY"

    monkeypatch.setattr(chat_mod, "CapabilityEntrySummaryBuilder", FakeCapabilityBuilder)
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        actions=[{"name": "system.health_check"}, {"name": "ai.chat"}],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("当前有哪些能力")

    assert reply == "CAPABILITY_BUILDER_REPLY"
    assert seen == [[{"name": "system.health_check"}, {"name": "ai.chat"}]]
    assert action_calls == []
    assert aicore.calls == []
    assert any("system.capabilities" in line for line in logs)


def test_capability_entry_summary_boundary_is_not_scattered():
    handle_source = inspect.getsource(GUIChatOrchestrator.handle_chat)

    assert hasattr(chat_mod, "CapabilityEntrySummaryBuilder")
    assert not hasattr(chat_mod, "_action_names")
    assert not hasattr(chat_mod, "_build_capability_reply")
    assert "CapabilityEntrySummaryBuilder(actions).build()" in handle_source
    assert "_action_names" not in handle_source
    assert "_build_capability_reply" not in handle_source


@pytest.mark.parametrize("question", ["你可以做什么", "你能帮我做什么", "你可以做啥", "当前有哪些能力"])
def test_capability_ux_questions_return_user_readable_summary(monkeypatch, question):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        actions=[{"name": "system.health_check"}, {"name": "memory.recall"}, {"name": "ai.chat"}],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat(question)

    assert "对话与问答" in reply
    assert "系统检测" in reply
    assert "记忆辅助" in reply
    assert "本地能力转接" in reply
    assert "当前可见动作示例" not in reply
    assert not INTERNAL_ACTION_NAME_RE.search(reply)
    assert action_calls == []
    assert aicore.calls == []
    assert any("system.capabilities" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)


def test_followup_capability_question_short_circuits(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        actions=["system.health_check"],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("还有呢")

    assert "我可以作为" in reply
    assert action_calls == []
    assert aicore.calls == []
    assert any("system.capabilities" in line for line in logs)


@pytest.mark.parametrize(
    "question",
    ["你可以做啥", "你都能干啥", "你会啥", "还能做啥", "还有啥", "当前有哪些能力"],
)
def test_colloquial_capability_questions_short_circuit(monkeypatch, question):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": "AI_OK"},
        actions=["system.health_check", "ai.chat"],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat(question)

    assert "本地数字中控助手" in reply
    assert "系统检测" in reply
    assert "当前可见动作示例" not in reply
    assert not INTERNAL_ACTION_NAME_RE.search(reply)
    assert action_calls == []
    assert aicore.calls == []
    assert any("system.capabilities" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)


def test_system_health_check_short_circuit_still_wins(monkeypatch):
    health = {
        "health": "DEGRADED",
        "modules": {
            "core": {"status": "OK"},
            "memory": {"status": "WARNING"},
        },
    }
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"system.health_check": health, "ai.chat": "AI_OK"},
        actions=["system.health_check"],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("打开系统检测")

    assert "系统健康：DEGRADED" in reply
    assert "模块总数：2" in reply
    assert "正常模块：core" in reply
    assert "警告/降级：memory" in reply
    assert "是否可正常使用：基本可用" in reply
    assert "是否建议立即处理：否" in reply
    assert "建议优先关注项：memory" in reply
    assert not reply.lstrip().startswith("{")
    assert '"health": "DEGRADED"' not in reply
    assert action_calls == ["system.health_check"]
    assert aicore.calls == []
    assert any("system.health_check [sys_detect]" in line for line in logs)
    assert any(
        "route=system.health_check" in line
        and "source=system.health_check" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )


def test_system_health_check_string_reply_has_trace(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"system.health_check": "系统健康：OK"},
        actions=["system.health_check"],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("打开系统检测")

    assert reply == "系统健康：OK"
    assert action_calls == ["system.health_check"]
    assert aicore.calls == []
    assert any(
        "route=system.health_check" in line
        and "source=system.health_check" in line
        and "short_circuit=true" in line
        for line in _trace_logs(logs)
    )


@pytest.mark.parametrize(
    ("question", "extra_terms"),
    [
        ("打开系统检测", ("系统健康：DEGRADED", "建议优先关注项：tts")),
        ("系统状态怎么样", ("系统健康：DEGRADED", "是否可正常使用：否")),
        ("哪些模块异常", ("异常/需关注模块：tts、memory、audio_consumer", "异常模块：tts")),
        ("建议优先处理什么", ("优先处理建议：tts", "是否建议立即处理：是")),
    ],
)
def test_system_status_questions_share_health_summary_truth(monkeypatch, question, extra_terms):
    health = {
        "health": "DEGRADED",
        "modules": {
            "core": {"status": "OK"},
            "tts": {"status": "ERROR", "reason": "player_failed"},
            "memory": {"status": "WARNING"},
            "audio_consumer": {"status": "STOPPED"},
        },
    }
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"system.health_check": health, "ai.chat": "AI_OK"},
        actions=["system.health_check", "ai.chat"],
        aicore=FakeAICore(chat_result="AICORE_OK", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat(question)

    assert "系统健康：DEGRADED" in reply
    assert "模块总数：4" in reply
    assert "正常模块：core" in reply
    assert "警告/降级：memory" in reply
    assert "异常模块：tts" in reply
    assert "停止模块：audio_consumer" in reply
    assert "建议优先关注项：tts" in reply
    for term in extra_terms:
        assert term in reply
    assert action_calls == ["system.health_check"]
    assert aicore.calls == []
    assert any("system.health_check" in line for line in logs)
    assert not any("chat route -> ai.chat" in line for line in logs)


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
    assert aicore.calls == ["memory_payload:你好", "get_status", "chat:你好"]
    ai_idx = next(i for i, line in enumerate(logs) if "🤖 chat route -> ai.chat" in line)
    aicore_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.chat" in line)
    assert ai_idx < aicore_idx
    assert any(
        "route=AICore.chat" in line
        and "source=AICore.chat" in line
        and "short_circuit=false" in line
        for line in _trace_logs(logs)
    )


def test_ai_chat_failure_then_fallback_to_action_aicore_chat_has_trace(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("boom"), "aicore.chat": "LEGACY_OK"},
        aicore=FakeAICore(chat_result="", ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "LEGACY_OK"
    assert action_calls == ["ai.chat", "aicore.chat"]
    assert aicore.calls == ["memory_payload:你好", "get_status", "chat:你好"]
    assert any(
        "route=action:aicore.chat" in line
        and "source=action:aicore.chat" in line
        and "short_circuit=false" in line
        for line in _trace_logs(logs)
    )


def test_aicore_chat_failure_skips_legacy_action_to_avoid_self_loop(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("ai down"), "aicore.chat": "LEGACY_OK"},
        aicore=FakeAICore(chat_exc=RuntimeError("aicore down"), ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "ASK_OK"
    assert action_calls == ["ai.chat"]
    assert aicore.calls == ["memory_payload:你好", "get_status", "chat:你好", "ask:你好"]
    assert any("已跳过 action:aicore.chat" in line for line in logs)


def test_aicore_ask_is_retained_probe_not_default_first_hop(monkeypatch):
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("ai down"), "aicore.chat": RuntimeError("legacy down")},
        aicore=FakeAICore(chat_exc=RuntimeError("aicore down"), ask_result="ASK_OK"),
    )

    reply = orch.handle_chat("你好")

    assert reply == "ASK_OK"
    assert action_calls == ["ai.chat"]
    assert aicore.calls == ["memory_payload:你好", "get_status", "chat:你好", "ask:你好"]
    ai_idx = next(i for i, line in enumerate(logs) if "🤖 chat route -> ai.chat" in line)
    chat_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.chat" in line)
    skip_idx = next(i for i, line in enumerate(logs) if "已跳过 action:aicore.chat" in line)
    ask_idx = next(i for i, line in enumerate(logs) if "🧠 chat route -> AICore.ask [retained probe]" in line)
    assert ai_idx < chat_idx < skip_idx < ask_idx
    assert any(
        "route=AICore.ask" in line
        and "source=AICore.ask" in line
        and "short_circuit=false" in line
        for line in _trace_logs(logs)
    )


def test_final_local_memory_fallback_has_trace(monkeypatch):
    local_calls = {"count": 0}
    orch, aicore, action_calls, logs = _make_orchestrator(
        monkeypatch,
        local_ok=False,
        action_plan={"ai.chat": RuntimeError("ai down"), "aicore.chat": ""},
        aicore=FakeAICore(chat_result="", ask_result=""),
    )

    def local_memory_after_fallback(*_args, **_kwargs):
        local_calls["count"] += 1
        return {
            "ok": local_calls["count"] > 1,
            "reply": "LOCAL_FALLBACK",
            "kind": "memory",
        }

    monkeypatch.setattr(chat_mod, "try_local_memory_answer", local_memory_after_fallback)

    reply = orch.handle_chat("你好")

    assert reply == "LOCAL_FALLBACK"
    assert action_calls == ["ai.chat", "aicore.chat"]
    assert aicore.calls == ["memory_payload:你好", "get_status", "chat:你好", "ask:你好"]
    assert any(
        "route=local_memory.final_fallback" in line
        and "source=memory.local" in line
        and "short_circuit=false" in line
        and "writeback=local_memory" in line
        for line in _trace_logs(logs)
    )


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


def test_gui_entry_uses_bridge_memory_pipeline_not_inline_copy():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")

    assert "from core.gui_bridge.gui_memory_bridge import install_memory_pipeline" in source
    assert "SANHUA_GUI_MEMORY_PIPELINE_CALL" in source
    assert "SANHUA_GUI_MEMORY_PIPELINE_V1_START" not in source
    assert "SANHUA_GUI_DISPLAY_SANITIZE_LOCAL_MEMORY_V1_START" not in source
    assert "_sanhua_gui_mem_collect_context" not in source
    assert "_sanhua_gui_try_local_memory_answer" not in source


def test_gui_entry_uses_live_alias_paths_not_force_patch():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")

    assert "def _try_load_aliases(self):" in source
    assert 'load_aliases_from_yaml("config/aliases.yaml", ACTION_MANAGER)' in source
    assert "SANHUA_GUI_ALIAS_FORCE_PATCH" not in source
    assert "_sanhua_yaml_load" not in source
    assert "_sanhua_register_aliases_into_dispatcher" not in source
    assert "def _load_aliases(" not in source


def test_gui_entry_does_not_install_runtime_aicore_bridge_copy():
    source = (PROJECT_ROOT / "entry/gui_entry/gui_main.py").read_text(encoding="utf-8")

    assert "class ModelRuntime" in source
    assert "class ActionRouter" in source
    assert "def _safe_call_action" in source
    assert "def refresh_modules" in source
    assert "def _chat_via_actions" in source
    assert "def handle_user_message" in source
    assert "GUIChatOrchestrator" in source
    assert "SANHUA_GUI_RUNTIME_AICORE_BRIDGE" not in source
    assert "_sanhua_gui_install_runtime_aicore_bridge" not in source
    assert "_sanhua_gui_bridge_" not in source
    assert "runtime.aicore" not in source
    assert "aicore.runtime" not in source
    assert "runtime.context" not in source
    assert "context.runtime" not in source
