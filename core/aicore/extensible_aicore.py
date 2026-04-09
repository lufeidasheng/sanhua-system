#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
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
    """适配 HealthMonitorPlus 到旧检查接口"""

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
    给 aicore_check.py 用的兼容层
    优先尝试 /logs，再尝试 /health
    """

    def __init__(self, base_url: str, timeout: int = 5):
        self.base_url = (base_url or "http://127.0.0.1:8080").rstrip("/")
        self.timeout = timeout

    def recent_logs(self, kind: str = "stderr", lines: int = 50) -> List[str]:
        lines = max(1, min(int(lines), 400))
        kind = (kind or "stderr").lower()

        try:
            url = urljoin(self.base_url + "/", "logs")
            resp = requests.get(url, params={"kind": kind, "lines": lines}, timeout=self.timeout)
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
    VERSION = "0.4.0-memory-autoconsolidate"

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
            "回答必须严格基于当前本地真实工程结构，禁止虚构模块、路径、方法和调用链。"
            "当前真实结构包括：core/memory_engine/memory_manager.py、"
            "core/prompt_engine/prompt_memory_bridge.py、"
            "core/aicore/extensible_aicore.py、"
            "data/memory/long_term.json、persona.json、session_cache.json、memory_index.json。"
            "记忆层与其他 core 并列存在，不依赖外部独立 memory service。"
            "回答风格要求：务实、系统化、可执行、优先贴合当前已落地实现。"
        )

        self.memory_manager = MemoryManager()
        self.prompt_memory_bridge = PromptMemoryBridge(memory_manager=self.memory_manager)

        self._ensure_default_session()

        # 自动整合记忆参数
        self._successful_store_turns = 0
        self._auto_consolidate_every = 3

    # =========================================================
    # basic helpers
    # =========================================================

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _consolidate_script(self) -> Path:
        return self._project_root() / "tools" / "consolidate_memory.py"

    # =========================
    # Auto maintenance helpers
    # =========================

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _run_memory_maintenance(self, trigger: str = "runtime") -> Dict[str, Any]:
        root = self._project_root()
        tool = root / "tools" / "run_memory_maintenance.py"

        if not tool.exists():
            return {
                "ok": False,
                "trigger": trigger,
                "reason": f"missing tool: {tool}",
            }

        now_ts = time.time()
        cooldown = float(getattr(self, "_memory_maintenance_cooldown_s", 15.0) or 15.0)
        last_ts = float(getattr(self, "_last_memory_maintenance_ts", 0.0) or 0.0)

        if trigger != "shutdown" and (now_ts - last_ts) < cooldown:
            return {
                "ok": False,
                "trigger": trigger,
                "reason": "cooldown",
                "cooldown_s": cooldown,
                "last_run_ts": last_ts,
            }

        cmd = [sys.executable, str(tool), "--root", str(root)]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            self._last_memory_maintenance_ts = now_ts
            self._last_memory_maintenance_result = {
                "ok": True,
                "trigger": trigger,
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-1200:],
                "stderr_tail": (proc.stderr or "")[-800:],
                "ran_at": now_ts,
            }
            return self._last_memory_maintenance_result
        except Exception as e:
            self._last_memory_maintenance_result = {
                "ok": False,
                "trigger": trigger,
                "reason": str(e),
                "ran_at": now_ts,
            }
            return self._last_memory_maintenance_result

    def _maybe_auto_memory_maintenance(self, action_name: str, status: str = "success") -> None:
        action_name = str(action_name or "").strip()
        status = str(status or "").strip().lower()

        if action_name == "aicore.chat":
            self._chat_turn_counter = int(getattr(self, "_chat_turn_counter", 0) or 0) + 1

            threshold = int(getattr(self, "auto_consolidate_every", 3) or 3)
            if self._chat_turn_counter >= threshold:
                result = self._run_memory_maintenance(trigger=f"chat.{status}")
                if result.get("ok"):
                    self._chat_turn_counter = 0

        elif action_name == "aicore.shutdown":
            self._run_memory_maintenance(trigger="shutdown")

    def _maintenance_runtime_status(self) -> Dict[str, Any]:
        return {
            "auto_every": int(getattr(self, "auto_consolidate_every", 3) or 3),
            "chat_turn_counter": int(getattr(self, "_chat_turn_counter", 0) or 0),
            "cooldown_s": float(getattr(self, "_memory_maintenance_cooldown_s", 15.0) or 15.0),
            "last_result": getattr(self, "_last_memory_maintenance_result", {}) or {},
        }

    def _ensure_default_session(self) -> None:
        try:
            active = self.memory_manager.get_active_session()
            if not active.get("session_id"):
                self.memory_manager.set_active_session(
                    session_id="aicore_default_session",
                    context_summary="AICore 默认会话"
                )
        except Exception as e:
            log.warning("ensure default session failed: %s", e)

    # =========================================================
    # memory prompt
    # =========================================================

    # =========================
    # Identity anchor helpers
    # =========================

    def _persona_json_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "memory" / "persona.json"

    def _load_user_profile_from_persona(self) -> Dict[str, Any]:
        path = self._persona_json_path()
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("读取 persona.json 失败: %s", e)
            return {}

        profile = data.get("user_profile", {})
        return profile if isinstance(profile, dict) else {}

    def get_user_identity(self) -> Dict[str, Any]:
        profile = self._load_user_profile_from_persona()

        name = str(profile.get("name", "") or "").strip()
        aliases = profile.get("aliases", [])
        preferred_style = profile.get("preferred_style", [])
        project_focus = profile.get("project_focus", [])
        stable_facts = profile.get("stable_facts", {})
        response_preferences = profile.get("response_preferences", {})
        notes = str(profile.get("notes", "") or "").strip()

        if not isinstance(aliases, list):
            aliases = []
        if not isinstance(preferred_style, list):
            preferred_style = []
        if not isinstance(project_focus, list):
            project_focus = []
        if not isinstance(stable_facts, dict):
            stable_facts = {}
        if not isinstance(response_preferences, dict):
            response_preferences = {}

        return {
            "name": name,
            "aliases": aliases,
            "preferred_style": preferred_style,
            "project_focus": project_focus,
            "stable_facts": stable_facts,
            "response_preferences": response_preferences,
            "notes": notes,
            "has_identity": bool(name),
        }

    def _build_identity_anchor_text(self) -> str:
        identity = self.get_user_identity()
        if not identity.get("has_identity"):
            return ""

        lines: List[str] = ["[身份锚点]"]

        name = str(identity.get("name", "")).strip()
        if name:
            lines.append(f"- 当前用户: {name}")

        aliases = identity.get("aliases", [])
        if aliases:
            lines.append("- 用户别名: " + ", ".join(str(x) for x in aliases if str(x).strip()))

        preferred_style = identity.get("preferred_style", [])
        if preferred_style:
            lines.append("- 回答风格偏好: " + ", ".join(str(x) for x in preferred_style if str(x).strip()))

        project_focus = identity.get("project_focus", [])
        if project_focus:
            lines.append("- 当前项目焦点: " + ", ".join(str(x) for x in project_focus if str(x).strip()))

        response_preferences = identity.get("response_preferences", {})
        tone = str(response_preferences.get("tone", "") or "").strip()
        structure = str(response_preferences.get("structure", "") or "").strip()
        verbosity = str(response_preferences.get("verbosity", "") or "").strip()

        if tone:
            lines.append(f"- 响应语气: {tone}")
        if structure:
            lines.append(f"- 响应结构: {structure}")
        if verbosity:
            lines.append(f"- 响应详细度: {verbosity}")

        stable_facts = identity.get("stable_facts", {})
        if stable_facts:
            identity_name = str(stable_facts.get("identity.name", "") or "").strip()
            primary_project = str(stable_facts.get("system.primary_project", "") or "").strip()
            response_pref = str(stable_facts.get("response.preference", "") or "").strip()

            if identity_name:
                lines.append(f"- 稳定事实.identity.name: {identity_name}")
            if primary_project:
                lines.append(f"- 稳定事实.system.primary_project: {primary_project}")
            if response_pref:
                lines.append(f"- 稳定事实.response.preference: {response_pref}")

        notes = str(identity.get("notes", "") or "").strip()
        if notes:
            lines.append(f"- 备注: {notes}")

        return "\n".join(lines).strip()

    def _compose_runtime_persona(self, base_persona: str) -> str:
        base = str(base_persona or "").strip()
        anchor = self._build_identity_anchor_text()

        if not anchor:
            return base

        if anchor in base:
            return base

        if not base:
            return anchor

        return f"{base}\n\n{anchor}"

    def build_memory_prompt(
        self,
        user_input: str,
        session_context: Any = None,
        system_persona: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        base_persona = system_persona if system_persona is not None else (self.system_persona or "")
        persona_text = self._compose_runtime_persona(base_persona)
        try:
            return self.prompt_memory_bridge.build_prompt(
                user_input=user_input,
                system_persona=persona_text,
                session_context=session_context,
                **kwargs,
            )
        except Exception as e:
            log.warning("build memory prompt failed, fallback raw input: %s", e)
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
            log.warning("build memory payload failed: %s", e)
            return {
                "user_input": user_input,
                "final_prompt": user_input,
                "memory_context_text": "",
                "selected_long_term_memories": [],
                "error": str(e),
            }

    # =========================================================
    # memory write helpers
    # =========================================================

    def record_chat_memory(self, role: str, content: str) -> None:
        try:
            self._ensure_default_session()
            self.memory_manager.append_recent_message(role=role, content=content)
        except Exception as e:
            log.warning("record chat memory failed: %s", e)

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
                result_summary=result_summary,
            )
            self._maybe_auto_memory_maintenance(
                action_name=action_name,
                status=status,
            )
        except Exception as e:
            log.warning("record action memory failed: %s", e)

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
            log.warning("add long term memory failed: %s", e)
            return None

    def memory_snapshot(self) -> Dict[str, Any]:
        try:
            return self.memory_manager.snapshot()
        except Exception as e:
            log.warning("memory snapshot failed: %s", e)
            return {"error": str(e)}

    def memory_health(self) -> Dict[str, Any]:
        try:
            return self.memory_manager.health_check()
        except Exception as e:
            log.warning("memory health failed: %s", e)
            return {"ok": False, "error": str(e)}

    # =========================================================
    # output cleaning and gate
    # =========================================================

    def _sanitize_llm_output(self, text: str) -> str:
        if text is None:
            return ""

        s = str(text).strip()
        if not s:
            return ""

        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE)

        final_marker_patterns = [
            r"<\|start\|>assistant<\|channel\|>final<\|message\|>",
            r"<\|channel\|>final<\|message\|>",
        ]
        for pattern in final_marker_patterns:
            m = re.search(pattern, s, flags=re.IGNORECASE)
            if m:
                s = s[m.end():].strip()
                break

        s = re.sub(
            r"<\|channel\|>analysis<\|message\|>.*?(?=(<\|start\|>assistant<\|channel\|>final<\|message\|>|$))",
            "",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )

        s = re.sub(r"<\|[^>]+?\|>", "", s)
        s = re.sub(r"<\|start\|>|<\|end\|>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"^\s*assistant\s*[:：]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n{3,}", "\n\n", s).strip()
        return s

    def _extract_method_like_tokens(self, text: str) -> List[str]:
        if not text:
            return []

        found = set()
        patterns = [
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(`",
        ]

        ignore = {
            "print", "len", "str", "dict", "list", "set", "int", "float",
            "open", "range", "max", "min", "sum", "any", "all",
            "append", "update", "get", "setdefault", "dumps", "loads", "run",
        }

        for pat in patterns:
            for item in re.findall(pat, text):
                if item in ignore:
                    continue
                found.add(item)

        return sorted(found)

    def _extract_path_refs(self, text: str) -> List[str]:
        if not text:
            return []
        pattern = re.compile(r"(?:[A-Za-z0-9_\-]+/)+[A-Za-z0-9_\-]+\.(?:py|json|yaml|yml|md|txt)")
        return sorted(set(pattern.findall(text)))

    def _build_repo_truth_index(self) -> Dict[str, Any]:
        cached = getattr(self, "_repo_truth_cache", None)
        if isinstance(cached, dict):
            return cached

        root = self._project_root()
        excluded = {
            ".git", "__pycache__", ".venv", "venv", "dependencies",
            "llama.cpp", "juyuan_models", "piper-master",
            "ollama_models", "rollback_snapshots", "build",
            "dist", "node_modules",
        }

        path_set = set()
        symbol_set = set()

        for p in root.rglob("*"):
            if not p.is_file():
                continue

            try:
                rel = p.relative_to(root)
            except Exception:
                continue

            if any(part in excluded for part in rel.parts):
                continue

            rel_str = rel.as_posix()
            path_set.add(rel_str)

            if p.suffix.lower() == ".py":
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue

                for name in re.findall(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, flags=re.MULTILINE):
                    symbol_set.add(name)

                for name in re.findall(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.MULTILINE):
                    symbol_set.add(name)

        cache = {"paths": path_set, "symbols": symbol_set}
        self._repo_truth_cache = cache
        return cache

    def _looks_like_internal_reasoning(self, text: str) -> bool:
        if not text:
            return False

        bad_patterns = [
            "<think>",
            "</think>",
            "The user asks:",
            "We need to respond",
            "首先，我需要回顾",
            "接下来，应该建议用户检查",
            "最后，需要给出",
            "根据已有的信息",
            "根据系统人格",
        ]
        return any(p in text for p in bad_patterns)

    def _looks_incomplete_answer(self, text: str) -> bool:
        if not text:
            return True

        stripped = text.strip()

        if stripped.count("```") % 2 == 1:
            return True

        if stripped.endswith(("：", ":", "```python", "```json", "```yaml", "```")):
            return True

        if "实现路径如下" in stripped and len(stripped) < 140:
            return True

        if len(stripped) < 30 and re.search(r"^\d+\.", stripped):
            return True

        return False

    def _contains_known_fake_structures(self, text: str) -> bool:
        if not text:
            return False

        bad_snippets = [
            "src/memory/manager.py",
            "src/aicore/core.py",
            "run_aicore.py",
            "HTTP/gRPC memory service",
            "PromptMemoryBridge(session_id=",
            "build_contextual_prompt",
            "_build_enhanced_prompt",
            "_call_model(",
            "_process_request",
            "get_context(",
            "get_relevant_memories(",
            "load_long_term_memory",
            "_save_long_term_memory",
            "_load_long_term",
            "index_memory(",
            "sync_memory(",
            "user_identity",
            "memory_type='long_term'",
            "threshold=0.75",
            "long_term_shard_",
            "msgpack",
            "LRU缓存",
            "分片存储",
            "序列化格式升级",
            "双向数据通道",
            "扩展模块",
            "增量压缩",
            "检索优化",
            "持久化绑定",
            "长期记忆关联",
            "字段级压缩",
            "分块压缩策略",
            "下游消费者",
            "会话级记忆隔离",
        ]
        if any(x in text for x in bad_snippets):
            return True

        suspicious_methods = {
            "_process_request",
            "get_context",
            "get_relevant_memories",
            "load_long_term_memory",
            "_save_long_term_memory",
            "_load_long_term",
            "index_memory",
            "sync_memory",
            "build_contextual_prompt",
            "_build_enhanced_prompt",
            "_call_model",
            "generate_response",
            "load_user_memory",
            "validate_answer",
            "check_memory_completeness",
            "validate_user",
            "load_user_identity",
            "set_memory",
            "get_memory",
            "save_to_long_term",
            "compress_memory",
            "decompress_data",
            "load_long_term",
            "update_identity",
        }

        detected = set(self._extract_method_like_tokens(text))
        if detected & suspicious_methods:
            return True

        allowed_private = {
            "_sanitize_llm_output",
            "_extract_method_like_tokens",
            "_extract_path_refs",
            "_build_repo_truth_index",
            "_looks_like_internal_reasoning",
            "_looks_incomplete_answer",
            "_contains_known_fake_structures",
            "_should_store_assistant_message",
            "_build_blocked_answer",
            "_run_memory_consolidation",
            "_maybe_auto_consolidate_memory",
            "_ensure_default_session",
            "_project_root",
            "_consolidate_script",
        }

        for token in detected:
            if token.startswith("_") and token not in allowed_private:
                return True

        repo = self._build_repo_truth_index()

        for path_ref in self._extract_path_refs(text):
            if path_ref not in repo["paths"]:
                return True

        allow_symbol_names = {
            "MemoryManager",
            "PromptMemoryBridge",
            "ExtensibleAICore",
            "build_memory_prompt",
            "build_memory_payload",
            "append_recent_message",
            "append_recent_action",
            "add_long_term_memory",
            "snapshot",
            "health_check",
        }

        for token in detected:
            if token in allow_symbol_names:
                continue
            if token not in repo["symbols"]:
                return True

        return False

    def _should_store_assistant_message(self, cleaned_text: str) -> bool:
        if not cleaned_text.strip():
            return False

        if self._looks_like_internal_reasoning(cleaned_text):
            return False

        if self._looks_incomplete_answer(cleaned_text):
            return False

        if self._contains_known_fake_structures(cleaned_text):
            return False

        return True

    def _build_blocked_answer(self, cleaned_text: str) -> str:
        preview = cleaned_text.strip()
        if len(preview) > 700:
            preview = preview[:700].rstrip() + " ...[truncated]"

        return (
            "⚠️ 模型给出了不完整或不可信的最终答案，已阻止写入记忆。\n\n"
            "以下是截断前内容预览：\n"
            f"{preview}"
        )

    # =========================================================
    # auto consolidate
    # =========================================================

    def _run_memory_consolidation(self) -> Dict[str, Any]:
        script = self._consolidate_script()
        if not script.exists():
            return {"ok": False, "error": f"script not found: {script}"}

        try:
            proc = subprocess.run(
                [sys.executable, str(script), "--root", str(self._project_root())],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=40,
            )
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _maybe_auto_consolidate_memory(self) -> None:
        self._successful_store_turns += 1

        if self._successful_store_turns < self._auto_consolidate_every:
            return

        self._successful_store_turns = 0
        result = self._run_memory_consolidation()

        if result.get("ok"):
            summary = "memory consolidation finished"
            stdout = result.get("stdout", "")
            if stdout:
                summary = stdout.splitlines()[0][:180]
            self.record_action_memory(
                action_name="memory.consolidate",
                status="success",
                result_summary=summary,
            )
        else:
            err = result.get("error") or result.get("stderr") or "unknown error"
            self.record_action_memory(
                action_name="memory.consolidate",
                status="failed",
                result_summary=str(err)[:180],
            )

    # =========================================================
    # core chat
    # =========================================================

    def chat(self, query: str) -> str:
        """
        真实对话入口:
        1. 记录用户输入
        2. 构建记忆增强 prompt
        3. 调后端
        4. 清洗输出
        5. 门禁判定
        6. 合格则写入记忆并触发自动 consolidate
        """
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
            raw_resp = backend.chat(final_prompt)
            raw_text = str(raw_resp)
            cleaned = self._sanitize_llm_output(raw_text)

            self._hm_plus.record_success()

            if not cleaned.strip():
                cleaned = raw_text.strip()

            if not self._should_store_assistant_message(cleaned):
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary="模型给出了不完整或不可信的最终答案",
                )
                return self._build_blocked_answer(cleaned or raw_text)

            self.record_chat_memory("assistant", cleaned)
            self.record_action_memory(
                action_name="aicore.chat",
                status="success",
                result_summary="后端调用成功",
            )

            self._maybe_auto_consolidate_memory()
            return cleaned

        except Exception as e:
            err = f"❌ 后端调用失败: {e}"
            self._hm_plus.record_failure(str(e))
            self.record_action_memory(
                action_name="aicore.chat",
                status="failed",
                result_summary=str(e),
            )
            return err

    # =========================================================
    # status / diagnostics
    # =========================================================

    def _get_runtime_model_truth(self) -> Dict[str, Any]:
        base_url = (getattr(self.controller, "base_url", "") or "http://127.0.0.1:8080").rstrip("/")

        result: Dict[str, Any] = {
            "ok": False,
            "base_url": base_url,
            "runtime_model": "",
            "models": [],
            "error": "",
        }

        try:
            resp = requests.get(urljoin(base_url + "/", "v1/models"), timeout=5)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}

            models: List[str] = []

            data_items = data.get("data", [])
            if isinstance(data_items, list):
                for item in data_items:
                    if not isinstance(item, dict):
                        continue
                    runtime_model = str(
                        item.get("id") or item.get("model") or item.get("name") or ""
                    ).strip()
                    if runtime_model:
                        models.append(runtime_model)

            if not models:
                model_items = data.get("models", [])
                if isinstance(model_items, list):
                    for item in model_items:
                        if not isinstance(item, dict):
                            continue
                        runtime_model = str(
                            item.get("model") or item.get("name") or item.get("id") or ""
                        ).strip()
                        if runtime_model:
                            models.append(runtime_model)

            models = list(dict.fromkeys(models))

            if models:
                result["ok"] = True
                result["runtime_model"] = models[0]
                result["models"] = models
            else:
                result["error"] = "no model returned from /v1/models"

        except Exception as e:
            result["error"] = str(e)

        return result

    def _augment_backend_status_with_runtime_truth(
        self,
        backend_status: Dict[str, Any],
        truth: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(backend_status, dict):
            return backend_status

        truth = truth if isinstance(truth, dict) else self._get_runtime_model_truth()

        compact_truth = {
            "ok": truth.get("ok", False),
            "runtime_model": truth.get("runtime_model", ""),
            "error": truth.get("error", ""),
        }

        for backend_name, entry in list(backend_status.items()):
            if not isinstance(entry, dict):
                continue

            config = entry.get("config", {})
            if not isinstance(config, dict):
                config = {}

            config_model = str(config.get("model_name", "")).strip()
            runtime_model = str(truth.get("runtime_model", "")).strip()

            entry["config_model_name"] = config_model
            entry["resolved_runtime_model"] = runtime_model
            entry["model_name_mismatch"] = bool(config_model and runtime_model and config_model != runtime_model)
            entry["runtime_truth"] = compact_truth

        return backend_status

    def get_status(self) -> Dict[str, Any]:
        active_session = {}
        try:
            active_session = self.memory_manager.get_active_session()
        except Exception:
            pass

        truth = self._get_runtime_model_truth()
        backend_status = self.backend_manager.get_backend_status()
        backend_status = self._augment_backend_status_with_runtime_truth(backend_status, truth)

        return {
            "version": self.VERSION,
            "uptime_s": int(time.time() - self.start_time),
            "backend_status": backend_status,
            "runtime_model_truth": truth,
            "health": self.health_monitor.health_report(),
            "memory_health": self.memory_health(),
            "identity_anchor": self.get_user_identity(),
            "maintenance_runtime": self._maintenance_runtime_status(),
            "active_session": {
                "session_id": active_session.get("session_id", ""),
                "last_active_at": active_session.get("last_active_at", ""),
                "context_summary": active_session.get("context_summary", ""),
            },
            "auto_consolidate_every": self._auto_consolidate_every,
            "successful_store_turns": self._successful_store_turns,
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
            # 退出前尽量做一次 consolidate
            result = self._run_memory_consolidation()
            if result.get("ok"):
                self.record_action_memory(
                    action_name="memory.consolidate",
                    status="success",
                    result_summary="shutdown before-exit consolidate finished",
                )
            else:
                self.record_action_memory(
                    action_name="memory.consolidate",
                    status="failed",
                    result_summary=str(result.get("error") or result.get("stderr") or "unknown error")[:180],
                )
        except Exception:
            pass

        try:
            self.record_action_memory(
                action_name="aicore.shutdown",
                status="success",
                result_summary="AICore 正常关闭",
            )
        except Exception:
            pass

# === SANHUA_DEGRADED_PATTERN_PATCH_V1_BEGIN ===
from pathlib import Path as _sanhua_Path
import json as _sanhua_json
import hashlib as _sanhua_hashlib
import re as _sanhua_re
from datetime import datetime as _sanhua_datetime


def _sanhua_aicore_project_root():
    return _sanhua_Path(__file__).resolve().parents[2]


def _sanhua_default_degraded_store():
    return {
        "version": "1.0",
        "store": "sanhua_degraded_patterns",
        "updated_at": "",
        "patterns": []
    }


def _sanhua_normalize_degraded_question(text):
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = _sanhua_re.sub(r"\s+", "", s)
    s = _sanhua_re.sub(r"[\"'`“”‘’$begin:math:display$$end:math:display$$begin:math:text$$end:math:text${}<>:：,，。！？!?\-_/\\\\|]+", "", s)
    return s[:500]


def _sanhua_degraded_patterns_path(self):
    return _sanhua_aicore_project_root() / "data" / "memory" / "degraded_patterns.json"


def _sanhua_load_degraded_patterns(self):
    path = self._degraded_patterns_path()
    if not path.exists():
        return _sanhua_default_degraded_store()

    try:
        data = _sanhua_json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _sanhua_default_degraded_store()
        if "patterns" not in data or not isinstance(data.get("patterns"), list):
            data["patterns"] = []
        return data
    except Exception:
        return _sanhua_default_degraded_store()


def _sanhua_save_degraded_patterns(self, payload):
    path = self._degraded_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["updated_at"] = _sanhua_datetime.now().astimezone().isoformat()
    if "version" not in payload:
        payload["version"] = "1.0"
    if "store" not in payload:
        payload["store"] = "sanhua_degraded_patterns"
    if "patterns" not in payload or not isinstance(payload.get("patterns"), list):
        payload["patterns"] = []
    path.write_text(
        _sanhua_json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sanhua_record_degraded_pattern(self, query, reason=""):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return {}

    payload = self._load_degraded_patterns()
    patterns = payload.setdefault("patterns", [])
    now_iso = _sanhua_datetime.now().astimezone().isoformat()
    query_excerpt = str(query or "").strip()[:160]
    reason_excerpt = str(reason or "").strip()[:300]

    hit = None
    for item in patterns:
        if str(item.get("normalized", "")).strip() == normalized:
            hit = item
            break

    if hit is None:
        hit = {
            "id": _sanhua_hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
            "query_excerpt": query_excerpt,
            "normalized": normalized,
            "count": 0,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "last_reason": reason_excerpt,
            "kind": "degraded_answer",
        }
        patterns.append(hit)

    hit["count"] = int(hit.get("count", 0)) + 1
    hit["last_seen"] = now_iso
    hit["last_reason"] = reason_excerpt
    if query_excerpt:
        hit["query_excerpt"] = query_excerpt

    patterns.sort(
        key=lambda x: (
            -int(x.get("count", 0)),
            str(x.get("last_seen", "")),
        )
    )
    payload["patterns"] = patterns[:200]
    self._save_degraded_patterns(payload)
    return hit


def _sanhua_get_degraded_pattern_matches(self, query, top_k=3):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return []

    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    scored = []

    for item in patterns:
        qn = str(item.get("normalized", "")).strip()
        if not qn:
            continue

        score = 0
        if qn == normalized:
            score = 100
        elif qn in normalized or normalized in qn:
            score = 80

        if score > 0:
            scored.append((score, int(item.get("count", 0)), item))

    scored.sort(key=lambda x: (-x[0], -x[1], str(x[2].get("last_seen", ""))))
    return [item for _, _, item in scored[:max(1, int(top_k))]]


def _sanhua_degraded_runtime_status(self):
    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    top = []
    for item in patterns[:5]:
        top.append({
            "id": item.get("id", ""),
            "query_excerpt": item.get("query_excerpt", ""),
            "count": int(item.get("count", 0)),
            "last_seen": item.get("last_seen", ""),
            "last_reason": item.get("last_reason", ""),
        })

    return {
        "path": str(self._degraded_patterns_path()),
        "patterns_count": len(patterns),
        "top_patterns": top,
    }


if "ExtensibleAICore" in globals():
    _SANHUA_AICORE_CLS = ExtensibleAICore

    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path", _sanhua_degraded_patterns_path)
    if not hasattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns", _sanhua_load_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns", _sanhua_save_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern"):
        setattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern", _sanhua_record_degraded_pattern)
    if not hasattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches"):
        setattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches", _sanhua_get_degraded_pattern_matches)
    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status", _sanhua_degraded_runtime_status)

    _orig_chat = getattr(_SANHUA_AICORE_CLS, "chat", None)
    if callable(_orig_chat) and not getattr(_orig_chat, "__sanhua_degraded_wrapped__", False) and not getattr(_orig_chat, "__sanhua_degraded_v2_chat_wrapped__", False):
        _base_chat = getattr(_orig_chat, "__wrapped__", None)
        if callable(_base_chat):
            _orig_chat = _base_chat
        def _wrapped_chat(self, query, *args, **kwargs):
            resp = _orig_chat(self, query, *args, **kwargs)
            txt = str(resp or "")

            degraded_markers = [
                "⚠️ 模型给出了不完整或不可信的最终答案",
                "⚠️ 模型给出了不完整的最终答案",
            ]
            if any(marker in txt for marker in degraded_markers):
                try:
                    self._record_degraded_pattern(query, txt[:300])
                except Exception as e:
                    try:
                        log.warning("记录 degraded pattern 失败: %s", e)
                    except Exception:
                        pass
            return resp

        _wrapped_chat.__sanhua_degraded_wrapped__ = True
        _wrapped_chat.__wrapped__ = _orig_chat
        setattr(_SANHUA_AICORE_CLS, "chat", _wrapped_chat)

    _orig_get_status = getattr(_SANHUA_AICORE_CLS, "get_status", None)
    if callable(_orig_get_status) and not getattr(_orig_get_status, "__sanhua_degraded_wrapped__", False):
        def _wrapped_get_status(self, *args, **kwargs):
            status = _orig_get_status(self, *args, **kwargs)
            if isinstance(status, dict):
                status = dict(status)
                try:
                    status["degraded_memory_runtime"] = self._degraded_runtime_status()
                except Exception as e:
                    status["degraded_memory_runtime"] = {"ok": False, "error": str(e)}
            return status

        _wrapped_get_status.__sanhua_degraded_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "get_status", _wrapped_get_status)

# === SANHUA_DEGRADED_PATTERN_PATCH_V1_END ===

# === SANHUA_DEGRADED_PATTERN_PATCH_V2_BEGIN ===
from pathlib import Path as _sanhua_Path
import json as _sanhua_json
import hashlib as _sanhua_hashlib
import re as _sanhua_re
from datetime import datetime as _sanhua_datetime


def _sanhua_aicore_project_root():
    return _sanhua_Path(__file__).resolve().parents[2]


def _sanhua_default_degraded_store():
    return {
        "version": "1.0",
        "store": "sanhua_degraded_patterns",
        "updated_at": "",
        "patterns": [],
    }


def _sanhua_normalize_degraded_question(text):
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = _sanhua_re.sub(r"\s+", "", s)
    s = _sanhua_re.sub(r"[\"'`“”‘’$begin:math:display$$end:math:display$$begin:math:text$$end:math:text${}<>:：,，。！？!?\-_/\\\\|]+", "", s)
    return s[:500]


def _sanhua_degraded_patterns_path(self):
    return _sanhua_aicore_project_root() / "data" / "memory" / "degraded_patterns.json"


def _sanhua_load_degraded_patterns(self):
    path = self._degraded_patterns_path()
    if not path.exists():
        return _sanhua_default_degraded_store()

    try:
        data = _sanhua_json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _sanhua_default_degraded_store()
        if "patterns" not in data or not isinstance(data.get("patterns"), list):
            data["patterns"] = []
        return data
    except Exception:
        return _sanhua_default_degraded_store()


def _sanhua_save_degraded_patterns(self, payload):
    path = self._degraded_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["updated_at"] = _sanhua_datetime.now().astimezone().isoformat()
    if "version" not in payload:
        payload["version"] = "1.0"
    if "store" not in payload:
        payload["store"] = "sanhua_degraded_patterns"
    if "patterns" not in payload or not isinstance(payload.get("patterns"), list):
        payload["patterns"] = []
    path.write_text(
        _sanhua_json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sanhua_record_degraded_pattern(self, query, reason=""):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return {}

    payload = self._load_degraded_patterns()
    patterns = payload.setdefault("patterns", [])
    now_iso = _sanhua_datetime.now().astimezone().isoformat()
    query_excerpt = str(query or "").strip()[:160]
    reason_excerpt = str(reason or "").strip()[:300]

    hit = None
    for item in patterns:
        if str(item.get("normalized", "")).strip() == normalized:
            hit = item
            break

    if hit is None:
        hit = {
            "id": _sanhua_hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
            "query_excerpt": query_excerpt,
            "normalized": normalized,
            "count": 0,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "last_reason": reason_excerpt,
            "kind": "degraded_answer",
        }
        patterns.append(hit)

    hit["count"] = int(hit.get("count", 0)) + 1
    hit["last_seen"] = now_iso
    hit["last_reason"] = reason_excerpt
    if query_excerpt:
        hit["query_excerpt"] = query_excerpt

    patterns.sort(
        key=lambda x: (
            -int(x.get("count", 0)),
            str(x.get("last_seen", "")),
        )
    )
    payload["patterns"] = patterns[:200]
    self._save_degraded_patterns(payload)
    return hit


def _sanhua_get_degraded_pattern_matches(self, query, top_k=2):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return []

    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    scored = []

    for item in patterns:
        qn = str(item.get("normalized", "")).strip()
        if not qn:
            continue

        score = 0
        if qn == normalized:
            score = 100
        elif qn in normalized or normalized in qn:
            score = 80

        if score > 0:
            scored.append((score, int(item.get("count", 0)), item))

    scored.sort(key=lambda x: (-x[0], -x[1], str(x[2].get("last_seen", ""))))
    return [item for _, _, item in scored[:max(1, int(top_k))]]


def _sanhua_inject_degraded_risk_block(self, final_prompt, user_input):
    prompt = str(final_prompt or "").strip()
    if not prompt:
        return prompt

    if "[风险问题提示]" in prompt:
        return prompt

    matches = self._get_degraded_pattern_matches(user_input, top_k=2)
    if not matches:
        return prompt

    lines = [
        "[风险问题提示]",
        "- 当前问题命中过往低可信回答模式。",
    ]

    for item in matches:
        excerpt = str(item.get("query_excerpt", "")).strip()
        count = int(item.get("count", 0))
        last_seen = str(item.get("last_seen", "")).strip()

        if excerpt:
            lines.append(f"- 命中问题: {excerpt}")
        if count:
            lines.append(f"- 历史命中次数: {count}")
        if last_seen:
            lines.append(f"- 最近命中时间: {last_seen}")

    lines.append("- 要求: 对此类问题必须更保守，只能基于当前真实工程结构回答；若无法确认，直接说明信息不足，不要编造。")
    risk_block = "\n".join(lines).strip()

    marker = "[用户当前输入]"
    if marker in prompt:
        return prompt.replace(marker, risk_block + "\n\n" + marker, 1)

    return prompt.rstrip() + "\n\n" + risk_block


def _sanhua_degraded_runtime_status(self):
    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    top = []
    for item in patterns[:5]:
        top.append({
            "id": item.get("id", ""),
            "query_excerpt": item.get("query_excerpt", ""),
            "count": int(item.get("count", 0)),
            "last_seen": item.get("last_seen", ""),
            "last_reason": item.get("last_reason", ""),
        })

    return {
        "path": str(self._degraded_patterns_path()),
        "patterns_count": len(patterns),
        "top_patterns": top,
    }


if "ExtensibleAICore" in globals():
    _SANHUA_AICORE_CLS = ExtensibleAICore

    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path", _sanhua_degraded_patterns_path)
    if not hasattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns", _sanhua_load_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns", _sanhua_save_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern"):
        setattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern", _sanhua_record_degraded_pattern)
    if not hasattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches"):
        setattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches", _sanhua_get_degraded_pattern_matches)
    if not hasattr(_SANHUA_AICORE_CLS, "_inject_degraded_risk_block"):
        setattr(_SANHUA_AICORE_CLS, "_inject_degraded_risk_block", _sanhua_inject_degraded_risk_block)
    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status", _sanhua_degraded_runtime_status)

    _orig_chat = getattr(_SANHUA_AICORE_CLS, "chat", None)
    if callable(_orig_chat) and not getattr(_orig_chat, "__sanhua_degraded_v2_chat_wrapped__", False) and not getattr(_orig_chat, "__sanhua_degraded_wrapped__", False):
        _base_chat = getattr(_orig_chat, "__wrapped__", None)
        if callable(_base_chat):
            _orig_chat = _base_chat
        def _wrapped_chat(self, query, *args, **kwargs):
            resp = _orig_chat(self, query, *args, **kwargs)
            txt = str(resp or "")
            degraded_markers = [
                "⚠️ 模型给出了不完整或不可信的最终答案",
                "⚠️ 模型给出了不完整的最终答案",
            ]
            if any(marker in txt for marker in degraded_markers):
                try:
                    self._record_degraded_pattern(query, txt[:300])
                except Exception as e:
                    try:
                        log.warning("记录 degraded pattern 失败: %s", e)
                    except Exception:
                        pass
            return resp

        _wrapped_chat.__sanhua_degraded_v2_chat_wrapped__ = True
        _wrapped_chat.__wrapped__ = _orig_chat
        setattr(_SANHUA_AICORE_CLS, "chat", _wrapped_chat)

    _orig_build_memory_prompt = getattr(_SANHUA_AICORE_CLS, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt) and not getattr(_orig_build_memory_prompt, "__sanhua_degraded_v2_prompt_wrapped__", False):
        def _wrapped_build_memory_prompt(self, user_input, *args, **kwargs):
            result = _orig_build_memory_prompt(self, user_input, *args, **kwargs)
            if isinstance(result, str):
                return self._inject_degraded_risk_block(result, user_input)
            return result

        _wrapped_build_memory_prompt.__sanhua_degraded_v2_prompt_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "build_memory_prompt", _wrapped_build_memory_prompt)

    _orig_build_memory_payload = getattr(_SANHUA_AICORE_CLS, "build_memory_payload", None)
    if callable(_orig_build_memory_payload) and not getattr(_orig_build_memory_payload, "__sanhua_degraded_v2_payload_wrapped__", False):
        def _wrapped_build_memory_payload(self, user_input, *args, **kwargs):
            payload = _orig_build_memory_payload(self, user_input, *args, **kwargs)
            if isinstance(payload, dict):
                final_prompt = payload.get("final_prompt")
                if isinstance(final_prompt, str):
                    payload = dict(payload)
                    payload["final_prompt"] = self._inject_degraded_risk_block(final_prompt, user_input)
            return payload

        _wrapped_build_memory_payload.__sanhua_degraded_v2_payload_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "build_memory_payload", _wrapped_build_memory_payload)

    _orig_get_status = getattr(_SANHUA_AICORE_CLS, "get_status", None)
    if callable(_orig_get_status) and not getattr(_orig_get_status, "__sanhua_degraded_v2_status_wrapped__", False):
        def _wrapped_get_status(self, *args, **kwargs):
            status = _orig_get_status(self, *args, **kwargs)
            if isinstance(status, dict):
                status = dict(status)
                try:
                    status["degraded_memory_runtime"] = self._degraded_runtime_status()
                except Exception as e:
                    status["degraded_memory_runtime"] = {"ok": False, "error": str(e)}
            return status

        _wrapped_get_status.__sanhua_degraded_v2_status_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "get_status", _wrapped_get_status)

# === SANHUA_DEGRADED_PATTERN_PATCH_V2_END ===

# === SANHUA_STATUS_RECURSION_HOTFIX_V1_BEGIN ===
from pathlib import Path as _sanhua_status_Path
import json as _sanhua_status_json


def _sanhua_status_project_root():
    return _sanhua_status_Path(__file__).resolve().parents[2]


def _sanhua_status_safe_runtime_truth(self):
    base_url = "http://127.0.0.1:8080"
    try:
        active = self.config.get_active_backends()
        if active:
            base_url = str(active[0].base_url or base_url).rstrip("/")
    except Exception:
        pass

    if base_url.endswith("/v1"):
        models_url = base_url + "/models"
        truth_base = base_url[:-3]
    else:
        models_url = base_url + "/v1/models"
        truth_base = base_url

    try:
        r = requests.get(models_url, timeout=3)
        r.raise_for_status()
        data = r.json()

        models = []

        if isinstance(data.get("models"), list):
            for item in data["models"]:
                if isinstance(item, dict):
                    models.append(str(item.get("model") or item.get("name") or item.get("id") or "").strip())

        if isinstance(data.get("data"), list):
            for item in data["data"]:
                if isinstance(item, dict):
                    models.append(str(item.get("id") or item.get("model") or item.get("name") or "").strip())

        models = [m for m in models if m]
        runtime_model = models[0] if models else ""

        return {
            "ok": True,
            "base_url": truth_base,
            "runtime_model": runtime_model,
            "models": models,
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "base_url": truth_base,
            "runtime_model": "",
            "models": [],
            "error": str(e),
        }


def _sanhua_status_safe_identity_anchor(self):
    # 1) 优先尝试已有属性/方法
    probe_methods = [
        "_get_identity_anchor",
        "_identity_anchor_status",
        "get_identity_anchor",
        "identity_anchor_status",
    ]
    for name in probe_methods:
        fn = getattr(self, name, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    probe_attrs = [
        "identity_anchor",
        "_identity_anchor",
    ]
    for name in probe_attrs:
        val = getattr(self, name, None)
        if isinstance(val, dict):
            return val

    # 2) 回退 persona.json
    path = _sanhua_status_project_root() / "data" / "memory" / "persona.json"
    if not path.exists():
        return {}

    try:
        data = _sanhua_status_json.loads(path.read_text(encoding="utf-8"))
        profile = data.get("user_profile", {}) if isinstance(data, dict) else {}
        if not isinstance(profile, dict):
            return {}

        anchor = {
            "name": profile.get("name", ""),
            "aliases": profile.get("aliases", []),
            "preferred_style": profile.get("preferred_style", []),
            "project_focus": profile.get("project_focus", []),
            "stable_facts": profile.get("stable_facts", {}),
            "response_preferences": profile.get("response_preferences", {}),
            "notes": profile.get("notes", ""),
        }
        anchor["has_identity"] = bool(anchor.get("name"))
        return anchor
    except Exception:
        return {}


def _sanhua_status_safe_maintenance_runtime(self):
    probe_methods = [
        "_maintenance_runtime_status",
        "get_maintenance_runtime",
    ]
    for name in probe_methods:
        fn = getattr(self, name, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    probe_attrs = [
        "_maintenance_runtime",
        "maintenance_runtime",
    ]
    for name in probe_attrs:
        val = getattr(self, name, None)
        if isinstance(val, dict):
            return val

    return {}


def _sanhua_status_safe_degraded_runtime(self):
    fn = getattr(self, "_degraded_runtime_status", None)
    if callable(fn):
        try:
            data = fn()
            if isinstance(data, dict):
                return data
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {}


def _sanhua_status_safe_get_status(self):
    active_session = {}
    try:
        if hasattr(self, "memory_manager") and self.memory_manager is not None:
            active_session = self.memory_manager.get_active_session() or {}
    except Exception:
        active_session = {}

    backend_status = {}
    try:
        if hasattr(self, "backend_manager") and self.backend_manager is not None:
            backend_status = self.backend_manager.get_backend_status() or {}
    except Exception as e:
        backend_status = {"error": str(e)}

    runtime_truth = _sanhua_status_safe_runtime_truth(self)

    status = {
        "version": getattr(self, "VERSION", ""),
        "uptime_s": int(time.time() - getattr(self, "start_time", time.time())),
        "backend_status": backend_status,
        "runtime_model_truth": runtime_truth,
        "health": {},
        "memory_health": {},
        "active_session": {
            "session_id": active_session.get("session_id", ""),
            "last_active_at": active_session.get("last_active_at", ""),
            "context_summary": active_session.get("context_summary", ""),
        },
    }

    try:
        if hasattr(self, "health_monitor") and self.health_monitor is not None:
            status["health"] = self.health_monitor.health_report()
    except Exception as e:
        status["health"] = {"ok": False, "error": str(e)}

    try:
        if hasattr(self, "memory_health") and callable(self.memory_health):
            status["memory_health"] = self.memory_health()
    except Exception as e:
        status["memory_health"] = {"ok": False, "error": str(e)}

    auto_every = getattr(self, "_auto_consolidate_every", None)
    if auto_every is not None:
        status["auto_consolidate_every"] = auto_every

    successful_store_turns = getattr(self, "_successful_store_turns", None)
    if successful_store_turns is not None:
        status["successful_store_turns"] = successful_store_turns

    identity_anchor = _sanhua_status_safe_identity_anchor(self)
    if identity_anchor:
        status["identity_anchor"] = identity_anchor

    maintenance_runtime = _sanhua_status_safe_maintenance_runtime(self)
    if maintenance_runtime:
        status["maintenance_runtime"] = maintenance_runtime

    degraded_runtime = _sanhua_status_safe_degraded_runtime(self)
    if degraded_runtime:
        status["degraded_memory_runtime"] = degraded_runtime

    return status


if "ExtensibleAICore" in globals():
    setattr(ExtensibleAICore, "get_status", _sanhua_status_safe_get_status)

# === SANHUA_STATUS_RECURSION_HOTFIX_V1_END ===

# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_BEGIN ===
import json as _sanhua_deg_json
import hashlib as _sanhua_deg_hashlib
from pathlib import Path as _sanhua_deg_Path
from datetime import datetime as _sanhua_deg_datetime, timezone as _sanhua_deg_timezone


def _sanhua_deg_project_root():
    return _sanhua_deg_Path(__file__).resolve().parents[2]


def _sanhua_deg_now_iso():
    return _sanhua_deg_datetime.now(_sanhua_deg_timezone.utc).astimezone().isoformat()


def _sanhua_deg_normalize_query(query):
    q = str(query or "").strip()
    q = " ".join(q.split())
    return q


def _sanhua_deg_excerpt(text, limit=80):
    s = str(text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[:limit] + " ..."


def _sanhua_deg_make_id(norm_query):
    return _sanhua_deg_hashlib.sha256(norm_query.encode("utf-8")).hexdigest()[:16]


def _sanhua_deg_file(self):
    root = _sanhua_deg_project_root()
    return root / "data" / "memory" / "degraded_patterns.json"


def _sanhua_deg_top_n(self):
    return int(getattr(self, "_degraded_patterns_top_n", 20) or 20)


def _sanhua_deg_cooldown_s(self):
    return float(getattr(self, "_degraded_patterns_cooldown_s", 300.0) or 300.0)


def _sanhua_deg_load(self):
    path = _sanhua_deg_file(self)
    if not path.exists():
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    try:
        data = _sanhua_deg_json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    if isinstance(data, list):
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": data
        }

    if not isinstance(data, dict):
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    data.setdefault("version", "1.0")
    data.setdefault("store", "sanhua_degraded_patterns")
    data.setdefault("updated_at", _sanhua_deg_now_iso())
    data.setdefault("patterns", [])

    if not isinstance(data["patterns"], list):
        data["patterns"] = []

    return data


def _sanhua_deg_save(self, data):
    path = _sanhua_deg_file(self)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _sanhua_deg_now_iso()
    path.write_text(
        _sanhua_deg_json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _sanhua_deg_sort_and_trim(self, patterns):
    def _key(x):
        return (
            int(x.get("count", 0)),
            str(x.get("last_seen", "")),
            str(x.get("query_norm", "")),
        )

    ordered = sorted(patterns, key=_key, reverse=True)
    return ordered[:_sanhua_deg_top_n(self)]


def _sanhua_deg_record(self, query, reason="", force=False):
    norm = _sanhua_deg_normalize_query(query)
    if not norm:
        return None

    now_ts = time.time()
    now_iso = _sanhua_deg_now_iso()
    cooldown_s = _sanhua_deg_cooldown_s(self)

    data = _sanhua_deg_load(self)
    patterns = data.get("patterns", [])

    target = None
    for item in patterns:
        if not isinstance(item, dict):
            continue
        item_norm = str(item.get("query_norm", "")).strip()
        if item_norm == norm:
            target = item
            break
        if not item_norm and str(item.get("query_excerpt", "")).strip() == _sanhua_deg_excerpt(norm):
            target = item
            break

    if target is None:
        target = {
            "id": _sanhua_deg_make_id(norm),
            "query_norm": norm,
            "query_excerpt": _sanhua_deg_excerpt(norm),
            "count": 1,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "last_seen_ts": now_ts,
            "last_reason": str(reason or "").strip(),
        }
        patterns.append(target)
    else:
        last_ts = float(target.get("last_seen_ts", 0.0) or 0.0)
        within_cooldown = (now_ts - last_ts) < cooldown_s

        if force or not within_cooldown:
            target["count"] = int(target.get("count", 0) or 0) + 1

        target["last_seen"] = now_iso
        target["last_seen_ts"] = now_ts
        target["last_reason"] = str(reason or "").strip()

        target.setdefault("id", _sanhua_deg_make_id(norm))
        target.setdefault("query_norm", norm)
        target.setdefault("query_excerpt", _sanhua_deg_excerpt(norm))
        target.setdefault("first_seen", now_iso)

    data["patterns"] = _sanhua_deg_sort_and_trim(self, patterns)
    _sanhua_deg_save(self, data)
    return target


def _sanhua_deg_runtime_status(self):
    data = _sanhua_deg_load(self)
    patterns = data.get("patterns", [])

    top_patterns = []
    for item in patterns[:5]:
        if not isinstance(item, dict):
            continue
        top_patterns.append({
            "id": item.get("id", ""),
            "query_excerpt": item.get("query_excerpt", ""),
            "count": int(item.get("count", 0) or 0),
            "last_seen": item.get("last_seen", ""),
            "last_reason": item.get("last_reason", ""),
        })

    return {
        "path": str(_sanhua_deg_file(self)),
        "patterns_count": len(patterns),
        "top_n": _sanhua_deg_top_n(self),
        "cooldown_s": _sanhua_deg_cooldown_s(self),
        "top_patterns": top_patterns,
    }


if "ExtensibleAICore" in globals():
    setattr(ExtensibleAICore, "_degraded_patterns_top_n", 20)
    setattr(ExtensibleAICore, "_degraded_patterns_cooldown_s", 300.0)

    # 统一覆盖，避免旧逻辑重复累加
    setattr(ExtensibleAICore, "_record_degraded_pattern", _sanhua_deg_record)
    setattr(ExtensibleAICore, "record_degraded_pattern", _sanhua_deg_record)
    setattr(ExtensibleAICore, "_degraded_runtime_status", _sanhua_deg_runtime_status)

# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_END ===

# === SANHUA_RISK_BLOCK_SLIM_V2_BEGIN ===
import re as _sanhua_risk_re


def _sanhua_slim_risk_block_text(final_prompt: str) -> str:
    text = str(final_prompt or "")
    if not text.strip():
        return text

    pattern = _sanhua_risk_re.compile(
        r"\n\[风险问题提示\]\n(?P<body>.*?)(?=\n\[用户当前输入\]|\n\[最后要求\]|\Z)",
        _sanhua_risk_re.DOTALL,
    )

    m = pattern.search(text)
    if not m:
        return text

    body = m.group("body") or ""

    count = None
    hit_query = ""
    last_seen = ""

    m_count = _sanhua_risk_re.search(r"历史命中次数:\s*(\d+)", body)
    if m_count:
        try:
            count = int(m_count.group(1))
        except Exception:
            count = None

    m_query = _sanhua_risk_re.search(r"命中问题:\s*(.+)", body)
    if m_query:
        hit_query = str(m_query.group(1)).strip()

    m_last = _sanhua_risk_re.search(r"最近命中时间:\s*(.+)", body)
    if m_last:
        last_seen = str(m_last.group(1)).strip()

    # 命中次数太低：整块直接删掉，减少 prompt 噪音
    if count is not None and count < 3:
        return text[:m.start()] + "\n" + text[m.end():]

    compact_lines = ["[风险提示]"]

    if count is not None:
        compact_lines.append(f"- 该问题命中过往低可信回答模式（{count}次）。")
    else:
        compact_lines.append("- 该问题命中过往低可信回答模式。")

    if hit_query:
        compact_lines.append(f"- 命中问题: {hit_query}")

    if last_seen:
        compact_lines.append(f"- 最近命中: {last_seen}")

    compact_lines.append("- 只基于当前真实工程结构回答；无法确认就直接说明信息不足。")

    compact = "\n" + "\n".join(compact_lines) + "\n"
    return text[:m.start()] + compact + text[m.end():]


if "ExtensibleAICore" in globals():
    _orig_build_memory_prompt = getattr(ExtensibleAICore, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt) and not getattr(_orig_build_memory_prompt, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_memory_prompt(self, *args, **kwargs):
            text = _orig_build_memory_prompt(self, *args, **kwargs)
            return _sanhua_slim_risk_block_text(text)

        _wrapped_build_memory_prompt._sanhua_risk_slim_wrapped = True
        ExtensibleAICore.build_memory_prompt = _wrapped_build_memory_prompt

    _orig_build_memory_payload = getattr(ExtensibleAICore, "build_memory_payload", None)
    if callable(_orig_build_memory_payload) and not getattr(_orig_build_memory_payload, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_memory_payload(self, *args, **kwargs):
            payload = _orig_build_memory_payload(self, *args, **kwargs)
            if isinstance(payload, dict):
                payload["final_prompt"] = _sanhua_slim_risk_block_text(payload.get("final_prompt", ""))
            return payload

        _wrapped_build_memory_payload._sanhua_risk_slim_wrapped = True
        ExtensibleAICore.build_memory_payload = _wrapped_build_memory_payload

# === SANHUA_RISK_BLOCK_SLIM_V2_END ===

# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_BEGIN ===

def _sanhua_hotfix_build_memory_prompt(self, user_input, session_context=None, system_persona=None, **kwargs):
    """
    热修复：
    直接走 PromptMemoryBridge 原始能力，绕过历史 wrapper 链，避免递归。
    """
    persona_text = system_persona if system_persona is not None else (getattr(self, "system_persona", "") or "")

    try:
        text = self.prompt_memory_bridge.build_prompt(
            user_input=user_input,
            system_persona=persona_text,
            session_context=session_context,
            **kwargs,
        )

        slim_fn = globals().get("_sanhua_slim_risk_block_text")
        if callable(slim_fn):
            try:
                text = slim_fn(text)
            except Exception:
                pass

        return text

    except Exception as e:
        try:
            log.warning("hotfix build_memory_prompt failed, fallback to raw user_input: %s", e)
        except Exception:
            pass
        return str(user_input or "")


def _sanhua_hotfix_build_memory_payload(self, user_input, session_context=None, system_persona=None, **kwargs):
    """
    热修复：
    直接走 PromptMemoryBridge 原始 payload 构建，绕过 build_memory_payload 的历史 wrapper 链。
    """
    persona_text = system_persona if system_persona is not None else (getattr(self, "system_persona", "") or "")

    try:
        payload = self.prompt_memory_bridge.build_prompt_payload(
            user_input=user_input,
            system_persona=persona_text,
            session_context=session_context,
            **kwargs,
        )

        if not isinstance(payload, dict):
            payload = {
                "user_input": str(user_input or ""),
                "final_prompt": str(user_input or ""),
                "memory_context_text": "",
                "selected_long_term_memories": [],
                "error": "bridge returned non-dict payload",
            }

        slim_fn = globals().get("_sanhua_slim_risk_block_text")
        if callable(slim_fn):
            try:
                payload["final_prompt"] = slim_fn(payload.get("final_prompt", ""))
            except Exception:
                pass

        return payload

    except Exception as e:
        try:
            log.warning("hotfix build_memory_payload failed, fallback payload: %s", e)
        except Exception:
            pass
        return {
            "user_input": str(user_input or ""),
            "final_prompt": str(user_input or ""),
            "memory_context_text": "",
            "selected_long_term_memories": [],
            "error": str(e),
        }


if "ExtensibleAICore" in globals():
    ExtensibleAICore.build_memory_prompt = _sanhua_hotfix_build_memory_prompt
    ExtensibleAICore.build_memory_payload = _sanhua_hotfix_build_memory_payload

# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_END ===

# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_BEGIN ===
import json as _sanhua_risk_json
from pathlib import Path as _sanhua_risk_Path


def _sanhua_load_degraded_patterns():
    try:
        root = _sanhua_risk_Path(__file__).resolve().parents[2]
        path = root / "data" / "memory" / "degraded_patterns.json"
        if not path.exists():
            return [], str(path)

        data = _sanhua_risk_json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, list):
            return data, str(path)

        if isinstance(data, dict):
            for key in ("patterns", "items", "entries", "data"):
                arr = data.get(key)
                if isinstance(arr, list):
                    return arr, str(path)

        return [], str(path)
    except Exception:
        return [], ""


def _sanhua_norm_text(s):
    return " ".join(str(s or "").strip().split())


def _sanhua_find_degraded_match(query: str):
    q = _sanhua_norm_text(query)
    if not q:
        return None

    patterns, _ = _sanhua_load_degraded_patterns()
    best = None
    best_score = (-1, -1)

    for item in patterns:
        if not isinstance(item, dict):
            continue

        excerpt = _sanhua_norm_text(item.get("query_excerpt", ""))
        if not excerpt:
            continue

        matched = (
            q == excerpt
            or excerpt in q
            or q in excerpt
        )
        if not matched:
            continue

        try:
            count = int(item.get("count", 0))
        except Exception:
            count = 0

        score = (count, len(excerpt))
        if score > best_score:
            best_score = score
            best = item

    return best


def _sanhua_build_compact_risk_block(query: str) -> str:
    item = _sanhua_find_degraded_match(query)
    if not item:
        return ""

    try:
        count = int(item.get("count", 0))
    except Exception:
        count = 0

    # 低于 3 次不注入，避免噪音
    if count < 3:
        return ""

    excerpt = str(item.get("query_excerpt", "")).strip()
    last_seen = str(item.get("last_seen", "")).strip()

    lines = ["[风险提示]"]
    lines.append(f"- 该问题命中过往低可信回答模式（{count}次）。")

    if excerpt:
        lines.append(f"- 命中问题: {excerpt}")

    if last_seen:
        lines.append(f"- 最近命中: {last_seen}")

    lines.append("- 只基于当前真实工程结构回答；无法确认就直接说明信息不足。")
    return "\n" + "\n".join(lines) + "\n"


def _sanhua_inject_compact_risk_block(final_prompt: str, user_input: str) -> str:
    text = str(final_prompt or "")
    if not text.strip():
        return text

    if "[风险提示]" in text or "[风险问题提示]" in text:
        return text

    block = _sanhua_build_compact_risk_block(user_input)
    if not block:
        return text

    marker = "\n[用户当前输入]\n"
    idx = text.find(marker)
    if idx != -1:
        return text[:idx] + block + text[idx:]

    marker2 = "\n[最后要求]\n"
    idx2 = text.find(marker2)
    if idx2 != -1:
        return text[:idx2] + block + text[idx2:]

    return text.rstrip() + "\n" + block


if "ExtensibleAICore" in globals():
    _orig_build_memory_prompt_for_risk = getattr(ExtensibleAICore, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt_for_risk) and not getattr(_orig_build_memory_prompt_for_risk, "_sanhua_compact_risk_wrapped", False):
        def _wrapped_build_memory_prompt_for_risk(self, user_input, *args, **kwargs):
            text = _orig_build_memory_prompt_for_risk(self, user_input, *args, **kwargs)
            return _sanhua_inject_compact_risk_block(text, user_input)

        _wrapped_build_memory_prompt_for_risk._sanhua_compact_risk_wrapped = True
        ExtensibleAICore.build_memory_prompt = _wrapped_build_memory_prompt_for_risk

    _orig_build_memory_payload_for_risk = getattr(ExtensibleAICore, "build_memory_payload", None)
    if callable(_orig_build_memory_payload_for_risk) and not getattr(_orig_build_memory_payload_for_risk, "_sanhua_compact_risk_wrapped", False):
        def _wrapped_build_memory_payload_for_risk(self, user_input, *args, **kwargs):
            payload = _orig_build_memory_payload_for_risk(self, user_input, *args, **kwargs)
            if isinstance(payload, dict):
                payload["final_prompt"] = _sanhua_inject_compact_risk_block(
                    payload.get("final_prompt", ""),
                    user_input,
                )
            return payload

        _wrapped_build_memory_payload_for_risk._sanhua_compact_risk_wrapped = True
        ExtensibleAICore.build_memory_payload = _wrapped_build_memory_payload_for_risk

# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_END ===
