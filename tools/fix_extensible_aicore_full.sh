#!/usr/bin/env bash
set -euo pipefail

TARGET="core/aicore/extensible_aicore.py"
BACKUP="${TARGET}.fixbak.$(date +%Y%m%d_%H%M%S)"

if [[ -f "$TARGET" ]]; then
  cp "$TARGET" "$BACKUP"
  echo "==> 已备份当前文件到: $BACKUP"
fi

cat > "$TARGET" <<'PY'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import re
import logging
from typing import Optional, Any, Dict, List
from urllib.parse import urljoin

import requests

from core.aicore.config import AICoreConfig
from core.aicore.backend_manager import BackendManager
from core.aicore.health_monitor import HealthMonitorPlus
from core.memory_engine.memory_manager import MemoryManager
from core.prompt_engine.prompt_memory_bridge import PromptMemoryBridge

log = logging.getLogger("ExtensibleAICore")


class _HealthAdapter:
    """Adapter for aicore_check expected interface."""

    def __init__(self, hm: HealthMonitorPlus):
        self._hm = hm

    def get_health_status(self) -> str:
        report = self._hm.health_report()
        if report.get("overload", {}).get("is_overloaded"):
            return "degraded"
        return "healthy"

    def health_report(self) -> Dict[str, Any]:
        return self._hm.health_report()


class _ControllerCompat:
    """
    Compatibility wrapper for aicore_check.py.
    Tries /logs first, then /health, otherwise returns [].
    """

    def __init__(self, base_url: str, timeout: int = 5):
        self.base_url = (base_url or "http://127.0.0.1:8080").rstrip("/")
        self.timeout = timeout

    def recent_logs(self, kind: str = "stderr", lines: int = 50) -> List[str]:
        lines = max(1, min(int(lines), 400))
        kind = (kind or "stderr").lower()

        try:
            url = urljoin(self.base_url + "/", "logs")
            resp = requests.get(
                url,
                params={"kind": kind, "lines": lines},
                timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                data = resp.json()
                got = data.get("lines")
                if isinstance(got, list):
                    return [str(x) for x in got][-lines:]
        except Exception:
            pass

        try:
            url = urljoin(self.base_url + "/", "health")
            resp = requests.get(url, timeout=self.timeout)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                key = "stderr_tail" if kind == "stderr" else "stdout_tail"
                got = data.get(key)
                if isinstance(got, list):
                    return [str(x) for x in got][-lines:]
        except Exception:
            pass

        return []


class ExtensibleAICore:
    VERSION = "0.3.5-answer-guarded"

    def __init__(self, config: Optional[AICoreConfig] = None):
        self.config = config or AICoreConfig.from_env()
        self.backend_manager = BackendManager(self.config)

        self._hm_plus = HealthMonitorPlus()
        self.health_monitor = _HealthAdapter(self._hm_plus)

        base_url = "http://127.0.0.1:8080"
        try:
            active = self.config.get_active_backends()
            if active:
                base_url = active[0].base_url
        except Exception:
            pass

        self.controller = _ControllerCompat(base_url=base_url, timeout=5)
        self.start_time = time.time()

        self.system_persona = (
            "你是三花聚顶系统的核心智能中枢。"
            "你必须严格基于当前项目真实结构回答，禁止虚构目录、文件、模块。"
            "当前真实结构包括："
            "core/memory_engine/memory_manager.py、"
            "core/prompt_engine/prompt_memory_bridge.py、"
            "core/aicore/extensible_aicore.py、"
            "data/memory/long_term.json、persona.json、session_cache.json、memory_index.json。"
            "记忆层与其他 core 并列存在，不依赖外部独立 memory service。"
            "ExtensibleAICore.chat() 在模型调用前构建记忆增强 prompt。"
            "禁止输出 src/memory/manager.py、src/aicore/core.py、run_aicore.py、"
            "HTTP/gRPC memory service、注册插件式微服务等当前项目中不存在的示例路径或架构。"
            "回答必须贴近当前工程实现，优先给出增量修改建议，而不是重新设计一套通用架构。"
            "回答风格要求：务实、系统化、可执行、贴近当前工程实现。"
        )

        self.memory_manager = MemoryManager()
        self.prompt_memory_bridge = PromptMemoryBridge(
            memory_manager=self.memory_manager
        )

        self._ensure_default_session()

    # =========================
    # internal utils
    # =========================

    @staticmethod
    def _truncate_text(text: Any, limit: int = 300) -> str:
        if text is None:
            return ""
        s = str(text).strip()
        if len(s) <= limit:
            return s
        return s[:limit] + " ...[truncated]"

    # =========================
    # memory helpers
    # =========================

    def _ensure_default_session(self) -> None:
        try:
            active = self.memory_manager.get_active_session()
            if not active.get("session_id"):
                self.memory_manager.set_active_session(
                    session_id="aicore_default_session",
                    context_summary="AICore 默认会话",
                )
        except Exception as e:
            log.warning("确保默认 session 失败: %s", e)

    def build_memory_prompt(
        self,
        user_input: str,
        session_context: Any = None,
        system_persona: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        persona_text = system_persona if system_persona is not None else (self.system_persona or "")
        try:
            return self.prompt_memory_bridge.build_prompt(
                user_input=user_input,
                system_persona=persona_text,
                session_context=session_context,
                **kwargs,
            )
        except Exception as e:
            log.warning("构建记忆增强 prompt 失败，回退原输入: %s", e)
            return user_input

    def build_memory_payload(
        self,
        user_input: str,
        session_context: Any = None,
        system_persona: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        persona_text = system_persona if system_persona is not None else (self.system_persona or "")
        try:
            return self.prompt_memory_bridge.build_prompt_payload(
                user_input=user_input,
                system_persona=persona_text,
                session_context=session_context,
                **kwargs,
            )
        except Exception as e:
            log.warning("构建记忆 payload 失败: %s", e)
            return {
                "user_input": user_input,
                "final_prompt": user_input,
                "memory_context_text": "",
                "selected_long_term_memories": [],
                "error": str(e),
            }

    def record_chat_memory(self, role: str, content: str) -> None:
        try:
            self._ensure_default_session()
            self.memory_manager.append_recent_message(role=role, content=content)
        except Exception as e:
            log.warning("记录会话记忆失败: %s", e)

    def record_action_memory(
        self,
        action_name: str,
        status: str = "success",
        result_summary: str = "",
    ) -> None:
        try:
            self._ensure_default_session()
            self.memory_manager.append_recent_action(
                action_name=action_name,
                status=status,
                result_summary=self._truncate_text(result_summary, 500),
            )
        except Exception as e:
            log.warning("记录动作记忆失败: %s", e)

    def add_long_term_memory(
        self,
        content: Any,
        memory_type: str = "fact",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self.memory_manager.add_long_term_memory(
                content=content,
                memory_type=memory_type,
                importance=importance,
                tags=tags,
                metadata=metadata,
            )
        except Exception as e:
            log.warning("写入长期记忆失败: %s", e)
            return None

    def memory_snapshot(self) -> Dict[str, Any]:
        try:
            return self.memory_manager.snapshot()
        except Exception as e:
            log.warning("获取记忆快照失败: %s", e)
            return {"error": str(e)}

    def memory_health(self) -> Dict[str, Any]:
        try:
            return self.memory_manager.health_check()
        except Exception as e:
            log.warning("获取记忆健康状态失败: %s", e)
            return {"ok": False, "error": str(e)}

    # =========================
    # output sanitizer / gating
    # =========================

    def _looks_like_internal_reasoning(self, text: str) -> bool:
        if not text:
            return False

        s = str(text).strip()
        lower_s = s.lower()

        if "<think>" in lower_s or "</think>" in lower_s:
            return True

        reasoning_markers = [
            "好的，用户再次",
            "首先，我需要",
            "根据系统人格",
            "接下来，应该建议",
            "用户提到",
            "回顾之前的回答",
            "确保回答符合",
            "确保建议符合",
            "可能用户",
            "需要检查",
            "关键点应该是",
        ]
        hits = sum(1 for marker in reasoning_markers if marker in s)
        return hits >= 2

    def _looks_incomplete_answer(self, text: str) -> bool:
        if not text:
            return True

        s = str(text).strip()
        if not s:
            return True

        if s.count("```") % 2 != 0:
            return True

        bad_endings = ("`", "：", ":", "，", ",", "（", "(", "|", "示例如下", "包括")
        if s.endswith(bad_endings):
            return True

        if len(s) < 260 and ("具体步骤如下" in s or "步骤如下" in s):
            return True

        normal_endings = ("。", "！", "？", ".", "!", "?", "”", "\"", "）", ")", "]", "】")
        if len(s) >= 80 and not s.endswith(normal_endings):
            return True

        return False

    def _sanitize_llm_output(self, text: str) -> str:
        """
        Sanitize model raw output:
        - remove closed <think>...</think>
        - if only unclosed <think> exists, return empty
        - remove control markers
        - reject remaining internal reasoning text
        """
        if text is None:
            return ""

        s = str(text).strip()
        if not s:
            return ""

        lower_s = s.lower()

        # closed think block
        if "<think>" in lower_s and "</think>" in lower_s:
            s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()
            lower_s = s.lower()

        # unclosed think block
        if "<think>" in lower_s and "</think>" not in lower_s:
            return ""

        final_marker_patterns = [
            r"<\|start\|>assistant<\|channel\|>final<\|message\|>",
            r"<\|channel\|>final<\|message\|>",
        ]
        for pattern in final_marker_patterns:
            match = re.search(pattern, s, flags=re.IGNORECASE)
            if match:
                s = s[match.end():].strip()
                break

        s = re.sub(
            r"<\|channel\|>analysis<\|message\|>.*?(?=(<\|start\|>assistant<\|channel\|>final<\|message\|>|$))",
            "",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )

        s = re.sub(r"<\|[^>]+?\|>", "", s)
        s = re.sub(r"^\s*assistant\s*[:：]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"<\|start\|>|<\|end\|>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n{3,}", "\n\n", s).strip()

        if self._looks_like_internal_reasoning(s):
            return ""

        return s

    def _should_store_assistant_message(self, text: str) -> bool:
        if text is None:
            return False

        s = str(text).strip()
        if not s:
            return False

        if len(s) < 40:
            return False

        if self._looks_like_internal_reasoning(s):
            return False

        if self._looks_incomplete_answer(s):
            return False

        dirty_markers = [
            "<|channel|>",
            "<|start|>",
            "<|end|>",
            "analysis<|message|>",
        ]
        if any(x in s for x in dirty_markers):
            return False

        lower_s = s.lower()

        real_terms = [
            "core/memory_engine/memory_manager.py",
            "core/prompt_engine/prompt_memory_bridge.py",
            "core/aicore/extensible_aicore.py",
            "data/memory",
            "memorymanager",
            "promptmemorybridge",
            "extensibleaicore",
            "session_cache",
            "long_term",
            "persona",
            "三花聚顶",
            "aicore",
        ]
        real_hits = sum(1 for term in real_terms if term.lower() in lower_s)
        if real_hits < 2:
            return False

        fake_or_generic_markers = [
            "src/memory/manager.py",
            "src/memory/bridge.py",
            "src/aicore/core.py",
            "memory service",
            "http/grpc",
            "grpc",
            "rest",
            "微服务",
            "独立服务",
            "部署 memory layer",
            "注册插件",
            "sqlite store",
            "redis store",
            "config.yaml",
            "run_aicore.py",
            "tests/test_memory_integration.py",
        ]
        generic_hits = sum(1 for x in fake_or_generic_markers if x.lower() in lower_s)
        if generic_hits >= 2:
            return False

        if "|" in s and "步骤" in s and real_hits < 3:
            return False

        if len(s) > 1800:
            return False

        return True

    # =========================
    # core chat
    # =========================

    def chat(self, query: str) -> str:
        self._ensure_default_session()
        self.record_chat_memory("user", query)

        final_prompt = self.build_memory_prompt(
            user_input=query,
            session_context={"source": "extensible_aicore.chat"},
        )

        backend = self.backend_manager.get_next_available_backend()
        if not backend:
            self._hm_plus.record_failure("no_backend")
            self.record_action_memory(
                action_name="aicore.chat",
                status="failed",
                result_summary="没有可用后端",
            )
            return "⚠️ 没有可用后端"

        try:
            resp = backend.chat(final_prompt)
            raw_resp_text = str(resp)
            resp_text = self._sanitize_llm_output(raw_resp_text)

            self._hm_plus.record_success()

            if not resp_text.strip():
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary="模型仅返回思考片段或无有效最终答案",
                )
                return "⚠️ 模型只返回了思考片段，没有产出可展示答案。建议减小上下文、提高 max_tokens，或切换更稳的模型。"

            if self._looks_incomplete_answer(resp_text):
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary="模型给出了不完整的最终答案",
                )
                return (
                    "⚠️ 模型给出了不完整的最终答案，已阻止写入记忆。\n\n"
                    "以下是截断前内容预览：\n"
                    f"{self._truncate_text(resp_text, 400)}"
                )

            if self._should_store_assistant_message(resp_text):
                self.record_chat_memory("assistant", resp_text)
            else:
                log.info("assistant 输出未写入记忆：质量门禁未通过")

            self.record_action_memory(
                action_name="aicore.chat",
                status="success",
                result_summary="后端调用成功",
            )

            return resp_text

        except Exception as e:
            err = f"❌ 后端调用失败: {e}"
            self._hm_plus.record_failure(str(e))
            self.record_action_memory(
                action_name="aicore.chat",
                status="failed",
                result_summary=str(e),
            )
            return err

    # =========================
    # status / diagnostics
    # =========================

    def get_status(self) -> Dict[str, Any]:
        active_session: Dict[str, Any] = {}
        try:
            active_session = self.memory_manager.get_active_session()
        except Exception:
            pass

        return {
            "version": self.VERSION,
            "uptime_s": int(time.time() - self.start_time),
            "backend_status": self.backend_manager.get_backend_status(),
            "health": self.health_monitor.health_report(),
            "memory_health": self.memory_health(),
            "active_session": {
                "session_id": active_session.get("session_id", ""),
                "last_active_at": active_session.get("last_active_at", ""),
                "context_summary": active_session.get("context_summary", ""),
            },
        }

    def debug_memory_prompt(
        self,
        query: str,
        session_context: Any = None,
    ) -> Dict[str, Any]:
        return self.build_memory_payload(
            user_input=query,
            session_context=session_context or {"source": "debug_memory_prompt"},
        )

    def shutdown(self) -> None:
        try:
            self.record_action_memory(
                action_name="aicore.shutdown",
                status="success",
                result_summary="AICore 正常关闭",
            )
        except Exception:
            pass
PY

python3 -m py_compile "$TARGET"
echo "✅ 已修复并通过语法检查: $TARGET"
