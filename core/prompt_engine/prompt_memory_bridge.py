#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple


class PromptMemoryBridge:
    """
    目标：
    1. 从 MemoryManager 快照中抽取真正可用的记忆上下文
    2. 优先使用 user_profile / session_summary / 高置信 long_term
    3. 降低 recent_messages 对 prompt 的污染
    4. 对外保持稳定接口：
       - build_prompt(...)
       - build_prompt_payload(...)
    """

    def __init__(
        self,
        memory_manager: Any,
        max_recent_messages: int = 4,
        max_recent_actions: int = 4,
        long_term_limit: int = 8,
        long_term_confidence_threshold: float = 0.85,
    ):
        self.memory_manager = memory_manager
        self.max_recent_messages = max_recent_messages
        self.max_recent_actions = max_recent_actions
        self.long_term_limit = long_term_limit
        self.long_term_confidence_threshold = long_term_confidence_threshold

    # =========================================================
    # Public API
    # =========================================================

    # =========================
    # Identity anchor helpers
    # =========================

    def _persona_json_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "memory" / "persona.json"

    def _load_user_profile(self) -> Dict[str, Any]:
        path = self._persona_json_path()
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 persona.json 失败: %s", e)
            return {}

        profile = data.get("user_profile", {})
        return profile if isinstance(profile, dict) else {}

    def _build_identity_anchor_block(self) -> str:
        profile = self._load_user_profile()
        if not profile:
            return ""

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

        if not name:
            return ""

        lines: List[str] = ["[身份锚点]"]
        lines.append(f"- 当前用户: {name}")

        alias_items = [str(x).strip() for x in aliases if str(x).strip()]
        if alias_items:
            lines.append("- 用户别名: " + ", ".join(alias_items))

        style_items = [str(x).strip() for x in preferred_style if str(x).strip()]
        if style_items:
            lines.append("- 回答风格偏好: " + ", ".join(style_items))

        project_items = [str(x).strip() for x in project_focus if str(x).strip()]
        if project_items:
            lines.append("- 当前项目焦点: " + ", ".join(project_items))

        tone = str(response_preferences.get("tone", "") or "").strip()
        structure = str(response_preferences.get("structure", "") or "").strip()
        verbosity = str(response_preferences.get("verbosity", "") or "").strip()

        if tone:
            lines.append(f"- 响应语气: {tone}")
        if structure:
            lines.append(f"- 响应结构: {structure}")
        if verbosity:
            lines.append(f"- 响应详细度: {verbosity}")

        identity_name = str(stable_facts.get("identity.name", "") or "").strip()
        primary_project = str(stable_facts.get("system.primary_project", "") or "").strip()
        response_pref = str(stable_facts.get("response.preference", "") or "").strip()

        if identity_name:
            lines.append(f"- 稳定事实.identity.name: {identity_name}")
        if primary_project:
            lines.append(f"- 稳定事实.system.primary_project: {primary_project}")
        if response_pref:
            lines.append(f"- 稳定事实.response.preference: {response_pref}")

        if notes:
            lines.append(f"- 备注: {notes}")

        return "\n".join(lines).strip()

    def _inject_identity_anchor(self, final_prompt: str) -> str:
        text = str(final_prompt or "").strip()
        if not text:
            return text

        identity_block = self._build_identity_anchor_block()
        if not identity_block:
            return text

        if "[身份锚点]" in text:
            return text

        insert_after_markers = [
            "[系统人格]",
            "[用户画像]",
        ]

        for marker in insert_after_markers:
            idx = text.find(marker)
            if idx != -1:
                marker_end = text.find("\n\n", idx)
                if marker_end != -1:
                    return text[:marker_end].rstrip() + "\n\n" + identity_block + "\n\n" + text[marker_end:].lstrip()

        return identity_block + "\n\n" + text

    def build_prompt(
        self,
        user_input: str,
        system_persona: Optional[str] = None,
        session_context: Any = None,
        **kwargs: Any,
    ) -> str:
        payload = self.build_prompt_payload(
            user_input=user_input,
            system_persona=system_persona,
            session_context=session_context,
            **kwargs,
        )
        return payload["final_prompt"]

    def build_prompt_payload(
        self,
        user_input: str,
        system_persona: Optional[str] = None,
        session_context: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        snapshot = self._safe_snapshot()

        persona_block = snapshot.get("persona", {}) or {}
        long_term_block = snapshot.get("long_term", {}) or {}
        session_cache_block = snapshot.get("session_cache", {}) or {}
        memory_index_block = snapshot.get("memory_index", {}) or {}

        active_session = session_cache_block.get("active_session", {}) or self._safe_get_active_session()

        stored_system_persona, user_profile = self._extract_persona_blocks(persona_block)
        merged_system_persona_text = self._merge_system_persona_text(
            runtime_system_persona=system_persona,
            stored_system_persona=stored_system_persona,
        )

        selected_long_term_memories = self._select_relevant_long_term_memories(
            memories=long_term_block.get("memories", []) or [],
            user_input=user_input,
            session_context=session_context,
        )

        session_summaries = self._extract_session_summaries(active_session)
        recent_messages = self._extract_recent_messages(active_session)
        recent_actions = self._extract_recent_actions(active_session)

        memory_context_text = self._build_memory_context_text(
            merged_system_persona_text=merged_system_persona_text,
            user_profile=user_profile,
            active_session=active_session,
            session_context=session_context,
            session_summaries=session_summaries,
            recent_messages=recent_messages,
            recent_actions=recent_actions,
            selected_long_term_memories=selected_long_term_memories,
            memory_index=memory_index_block,
        )

        final_prompt = self._compose_final_prompt(
            memory_context_text=memory_context_text,
            user_input=user_input,
        )

        return {
            "user_input": user_input,
            "final_prompt": self._inject_identity_anchor(final_prompt),
            "memory_context_text": memory_context_text,
            "selected_long_term_memories": selected_long_term_memories,
            "user_profile": user_profile,
            "active_session": active_session,
            "session_summaries": session_summaries,
            "recent_messages": recent_messages,
            "recent_actions": recent_actions,
            "memory_index": memory_index_block,
        }

    # =========================================================
    # Snapshot / extraction
    # =========================================================

    def _safe_snapshot(self) -> Dict[str, Any]:
        try:
            snap = self.memory_manager.snapshot()
            if isinstance(snap, dict):
                return snap
        except Exception:
            pass
        return {}

    def _safe_get_active_session(self) -> Dict[str, Any]:
        try:
            active = self.memory_manager.get_active_session()
            if isinstance(active, dict):
                return active
        except Exception:
            pass
        return {}

    def _extract_persona_blocks(self, persona_block: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        兼容两种结构：
        1. 新结构：system_persona / user_profile
        2. 旧结构：persona
        """
        stored_system_persona: Dict[str, Any] = {}
        user_profile: Dict[str, Any] = {}

        if isinstance(persona_block.get("system_persona"), dict):
            stored_system_persona = persona_block.get("system_persona", {}) or {}

        if isinstance(persona_block.get("user_profile"), dict):
            user_profile = persona_block.get("user_profile", {}) or {}

        old_persona = persona_block.get("persona")
        if isinstance(old_persona, dict):
            if not stored_system_persona:
                stored_system_persona = old_persona
            if not user_profile:
                user_profile = {
                    "name": "",
                    "aliases": [],
                    "preferred_style": [],
                    "response_preferences": {},
                    "project_focus": [],
                    "stable_facts": {},
                    "notes": "",
                    "updated_at": "",
                }

        if not isinstance(stored_system_persona, dict):
            stored_system_persona = {}
        if not isinstance(user_profile, dict):
            user_profile = {}

        return stored_system_persona, user_profile

    def _extract_session_summaries(self, active_session: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = active_session.get("session_summaries", []) or []
        out: List[Dict[str, Any]] = []

        if not isinstance(raw, list):
            return out

        for item in raw[-3:]:
            if not isinstance(item, dict):
                continue
            summary_text = str(item.get("summary_text", "")).strip()
            if not summary_text:
                continue
            out.append({
                "id": item.get("id", ""),
                "created_at": item.get("created_at", ""),
                "summary_text": summary_text,
                "summary_points": item.get("summary_points", []),
            })
        return out

    def _extract_recent_messages(self, active_session: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = active_session.get("recent_messages", []) or []
        out: List[Dict[str, Any]] = []

        if not isinstance(raw, list):
            return out

        for item in raw[-self.max_recent_messages:]:
            if not isinstance(item, dict):
                continue

            role = str(item.get("role", "")).strip()
            content = self._sanitize_text(str(item.get("content", "")).strip())
            if not role or not content:
                continue
            if self._looks_polluted(content):
                continue

            out.append({
                "id": item.get("id", ""),
                "role": role,
                "content": self._shorten(content, 240),
                "timestamp": item.get("timestamp", ""),
            })

        return out

    def _extract_recent_actions(self, active_session: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = active_session.get("recent_actions", []) or []
        out: List[Dict[str, Any]] = []

        if not isinstance(raw, list):
            return out

        for item in raw[-self.max_recent_actions:]:
            if not isinstance(item, dict):
                continue

            action_name = str(item.get("action_name", "")).strip()
            status = str(item.get("status", "")).strip()
            result_summary = self._sanitize_text(str(item.get("result_summary", "")).strip())

            if not action_name:
                continue

            out.append({
                "id": item.get("id", ""),
                "action_name": action_name,
                "status": status,
                "result_summary": self._shorten(result_summary, 180),
                "timestamp": item.get("timestamp", ""),
            })

        return out

    # =========================================================
    # Long-term memory selection
    # =========================================================

    def _select_relevant_long_term_memories(
        self,
        memories: List[Dict[str, Any]],
        user_input: str,
        session_context: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(memories, list):
            return []

        selected: List[Tuple[float, Dict[str, Any]]] = []

        for item in memories:
            if not isinstance(item, dict):
                continue

            confidence = float(item.get("confidence", item.get("importance", 0.0)) or 0.0)
            if confidence < self.long_term_confidence_threshold:
                continue

            norm = self._normalize_long_term_item(item)
            score = self._score_memory_item(norm, user_input, session_context)

            # identity / preference / project_focus / architecture_fact 优先
            if norm["type"] in {"identity", "preference", "project_focus", "architecture_fact"}:
                score += 2.0

            if score <= 0:
                continue

            selected.append((score, norm))

        selected.sort(key=lambda x: (-x[0], -x[1].get("confidence", 0.0), x[1].get("updated_at", "")))
        return [item for _, item in selected[: self.long_term_limit]]

    def _normalize_long_term_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        type_ = str(item.get("type", item.get("memory_type", "fact"))).strip() or "fact"
        key = str(item.get("key", "")).strip()
        value = item.get("value", item.get("content", ""))
        content = str(item.get("content", "")).strip()
        confidence = float(item.get("confidence", item.get("importance", 0.0)) or 0.0)
        tags = item.get("tags", []) if isinstance(item.get("tags", []), list) else []

        if not content and key:
            content = f"{type_}:{key}={value}"

        return {
            "id": item.get("id", ""),
            "type": type_,
            "key": key,
            "value": value,
            "content": content,
            "confidence": confidence,
            "source": str(item.get("source", "")).strip(),
            "tags": tags,
            "updated_at": str(item.get("updated_at", item.get("timestamp", ""))).strip(),
            "metadata": item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {},
        }

    def _score_memory_item(
        self,
        item: Dict[str, Any],
        user_input: str,
        session_context: Any,
    ) -> float:
        score = 0.0
        text = " ".join([
            str(item.get("type", "")),
            str(item.get("key", "")),
            str(item.get("value", "")),
            str(item.get("content", "")),
            " ".join(item.get("tags", [])),
        ]).lower()

        keywords = self._extract_keywords(user_input)
        for kw in keywords:
            if kw and kw.lower() in text:
                score += 1.5

        if isinstance(session_context, dict):
            for v in session_context.values():
                sv = str(v).strip().lower()
                if sv and sv in text:
                    score += 0.8

        # 用户身份、偏好、项目焦点默认加权
        if item.get("type") == "identity" and item.get("key") == "name":
            score += 5.0
        if item.get("type") == "preference" and item.get("key") == "preferred_style":
            score += 4.0
        if item.get("type") == "project_focus" and item.get("key") == "project_focus":
            score += 3.0
        if item.get("type") == "architecture_fact":
            score += 2.5

        # 用户当前输入包含记忆/系统/架构/AICore 之类时，架构事实再加权
        if any(x in user_input for x in ["记忆", "AICore", "架构", "系统", "整改"]):
            if item.get("type") in {"architecture_fact", "project_focus"}:
                score += 1.5

        score += float(item.get("confidence", 0.0))
        return score

    # =========================================================
    # Prompt building
    # =========================================================

    def _build_memory_context_text(
        self,
        merged_system_persona_text: str,
        user_profile: Dict[str, Any],
        active_session: Dict[str, Any],
        session_context: Any,
        session_summaries: List[Dict[str, Any]],
        recent_messages: List[Dict[str, Any]],
        recent_actions: List[Dict[str, Any]],
        selected_long_term_memories: List[Dict[str, Any]],
        memory_index: Dict[str, Any],
    ) -> str:
        sections: List[str] = []

        if merged_system_persona_text:
            sections.append(f"[系统人格]\n{merged_system_persona_text}")

        user_profile_text = self._build_user_profile_text(user_profile)
        if user_profile_text:
            sections.append(f"[用户画像]\n{user_profile_text}")

        active_session_text = self._build_active_session_text(active_session)
        if active_session_text:
            sections.append(f"[当前会话]\n{active_session_text}")

        if session_context:
            sections.append(
                "[外部会话上下文]\n" +
                json.dumps(session_context, ensure_ascii=False, indent=2)
            )

        if session_summaries:
            lines = []
            for item in session_summaries:
                summary_text = str(item.get("summary_text", "")).strip()
                if summary_text:
                    lines.append(f"- {summary_text}")
            if lines:
                sections.append("[会话摘要]\n" + "\n".join(lines))

        if selected_long_term_memories:
            lines = []
            for item in selected_long_term_memories:
                line = (
                    f"- type={item.get('type', '')} | "
                    f"key={item.get('key', '')} | "
                    f"confidence={item.get('confidence', 0.0)} | "
                    f"value={item.get('value', '')}"
                )
                content = str(item.get("content", "")).strip()
                if content:
                    line += f"\n  content: {content}"
                lines.append(line)
            sections.append("[长期相关记忆]\n" + "\n".join(lines))

        if recent_messages:
            lines = [f"- [{m['role']}] {m['content']}" for m in recent_messages]
            sections.append("[最近消息片段]\n" + "\n".join(lines))

        if recent_actions:
            lines = []
            for a in recent_actions:
                line = f"- {a['action_name']} | {a['status']}"
                if a["result_summary"]:
                    line += f" | {a['result_summary']}"
                lines.append(line)
            sections.append("[最近动作片段]\n" + "\n".join(lines))

        index_text = self._build_memory_index_hint(memory_index)
        if index_text:
            sections.append(f"[记忆索引提示]\n{index_text}")

        sections.append(
            "[输出约束]\n"
            "1. 严格基于当前真实工程结构回答。\n"
            "2. 禁止虚构不存在的路径、模块、方法、调用链。\n"
            "3. 不要输出<think>、推理草稿、analysis通道内容。\n"
            "4. 优先给增量修改建议，而不是重新发明架构。\n"
            "5. 若信息不足，直接说明不足，不要编造。"
        )

        return "\n\n".join(sections).strip()

    def _compose_final_prompt(self, memory_context_text: str, user_input: str) -> str:
        parts = []
        if memory_context_text:
            parts.append(memory_context_text)
        parts.append(f"[用户当前输入]\n{user_input}")
        parts.append("[最后要求]\n只输出最终答案，不要输出思考过程。")
        return "\n\n".join(parts).strip()

    def _build_user_profile_text(self, user_profile: Dict[str, Any]) -> str:
        if not isinstance(user_profile, dict):
            return ""

        lines = []

        name = str(user_profile.get("name", "")).strip()
        if name:
            lines.append(f"- 名字: {name}")

        aliases = user_profile.get("aliases", [])
        if isinstance(aliases, list) and aliases:
            lines.append(f"- 别名: {', '.join(str(x) for x in aliases if str(x).strip())}")

        styles = user_profile.get("preferred_style", [])
        if isinstance(styles, list) and styles:
            lines.append(f"- 回答风格偏好: {', '.join(str(x) for x in styles if str(x).strip())}")

        response_preferences = user_profile.get("response_preferences", {})
        if isinstance(response_preferences, dict) and response_preferences:
            for k, v in response_preferences.items():
                lines.append(f"- 响应偏好.{k}: {v}")

        project_focus = user_profile.get("project_focus", [])
        if isinstance(project_focus, list) and project_focus:
            lines.append(f"- 当前项目焦点: {', '.join(str(x) for x in project_focus if str(x).strip())}")

        stable_facts = user_profile.get("stable_facts", {})
        if isinstance(stable_facts, dict) and stable_facts:
            for k, v in stable_facts.items():
                lines.append(f"- 稳定事实.{k}: {v}")

        notes = str(user_profile.get("notes", "")).strip()
        if notes:
            lines.append(f"- 备注: {notes}")

        return "\n".join(lines).strip()

    def _build_active_session_text(self, active_session: Dict[str, Any]) -> str:
        if not isinstance(active_session, dict):
            return ""

        lines = []
        session_id = str(active_session.get("session_id", "")).strip()
        context_summary = str(active_session.get("context_summary", "")).strip()
        started_at = str(active_session.get("started_at", "")).strip()
        last_active_at = str(active_session.get("last_active_at", "")).strip()

        if session_id:
            lines.append(f"- session_id: {session_id}")
        if started_at:
            lines.append(f"- started_at: {started_at}")
        if last_active_at:
            lines.append(f"- last_active_at: {last_active_at}")
        if context_summary:
            lines.append(f"- context_summary: {context_summary}")

        return "\n".join(lines).strip()

    def _build_memory_index_hint(self, memory_index: Dict[str, Any]) -> str:
        if not isinstance(memory_index, dict):
            return ""

        index = memory_index.get("index", {})
        stats = memory_index.get("stats", {})

        lines = []

        if isinstance(stats, dict) and stats:
            long_term_count = stats.get("long_term_count")
            session_summary_count = stats.get("session_summary_count")
            user_name_present = stats.get("user_name_present")
            preferred_style_count = stats.get("preferred_style_count")

            if long_term_count is not None:
                lines.append(f"- long_term_count: {long_term_count}")
            if session_summary_count is not None:
                lines.append(f"- session_summary_count: {session_summary_count}")
            if user_name_present is not None:
                lines.append(f"- user_name_present: {user_name_present}")
            if preferred_style_count is not None:
                lines.append(f"- preferred_style_count: {preferred_style_count}")

        if isinstance(index, dict):
            memory_keys = index.get("memory_keys", [])
            if isinstance(memory_keys, list) and memory_keys:
                lines.append(f"- memory_keys: {', '.join(str(x) for x in memory_keys[:8])}")

        return "\n".join(lines).strip()

    def _merge_system_persona_text(
        self,
        runtime_system_persona: Optional[str],
        stored_system_persona: Dict[str, Any],
    ) -> str:
        parts: List[str] = []

        runtime_text = str(runtime_system_persona or "").strip()
        if runtime_text:
            parts.append(runtime_text)

        if isinstance(stored_system_persona, dict) and stored_system_persona:
            stored_lines = []
            name = str(stored_system_persona.get("name", "")).strip()
            system_identity = str(stored_system_persona.get("system_identity", "")).strip()
            style = str(stored_system_persona.get("style", "")).strip()
            goals = stored_system_persona.get("goals", [])
            constraints = stored_system_persona.get("constraints", [])
            traits = stored_system_persona.get("traits", [])
            notes = str(stored_system_persona.get("notes", "")).strip()

            if name:
                stored_lines.append(f"系统名：{name}")
            if system_identity:
                stored_lines.append(f"系统身份：{system_identity}")
            if style:
                stored_lines.append(f"系统风格：{style}")
            if isinstance(goals, list) and goals:
                stored_lines.append(f"系统目标：{', '.join(str(x) for x in goals if str(x).strip())}")
            if isinstance(constraints, list) and constraints:
                stored_lines.append(f"系统约束：{', '.join(str(x) for x in constraints if str(x).strip())}")
            if isinstance(traits, list) and traits:
                stored_lines.append(f"系统特征：{', '.join(str(x) for x in traits if str(x).strip())}")
            if notes:
                stored_lines.append(f"系统备注：{notes}")

            if stored_lines:
                parts.append("\n".join(stored_lines))

        # 去重
        uniq_parts = []
        seen = set()
        for p in parts:
            if p in seen:
                continue
            seen.add(p)
            uniq_parts.append(p)

        return "\n".join(uniq_parts).strip()

    # =========================================================
    # Text utilities
    # =========================================================

    def _sanitize_text(self, text: str) -> str:
        if not text:
            return ""

        s = str(text)

        # 去掉 think 块
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE)

        # 去掉通道标记
        s = re.sub(r"<\|channel\|>analysis<\|message\|>.*?(?=(<\|channel\|>final<\|message\|>|$))", "", s, flags=re.DOTALL | re.IGNORECASE)
        s = re.sub(r"<\|[^>]+?\|>", "", s)

        # 去掉常见残留
        s = re.sub(r"^\s*assistant\s*[:：]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    def _looks_polluted(self, text: str) -> bool:
        if not text:
            return False

        bad_snippets = [
            "<think>",
            "</think>",
            "<|channel|>analysis",
            "The user asks:",
            "We need to respond",
            "src/memory/manager.py",
            "src/aicore/core.py",
            "run_aicore.py",
            "HTTP/gRPC memory service",
            "build_contextual_prompt",
            "_build_enhanced_prompt",
            "_call_model(",
            "PromptMemoryBridge(session_id=",
        ]

        for snippet in bad_snippets:
            if snippet in text:
                return True

        # 明显是半截结构化幻觉时也拦
        if "实现路径如下" in text and "```python" in text and "src/" in text:
            return True

        return False

    def _shorten(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 12].rstrip() + " ...[truncated]"

    def _extract_keywords(self, text: str) -> List[str]:
        if not text:
            return []

        raw = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]+", text)
        deny = {
            "现在", "应该", "怎么", "这个", "那个", "就是", "以及", "我们",
            "你们", "他们", "一下", "一下子", "当前", "可以", "需要", "一个",
            "进行", "因为", "所以", "然后", "如果", "但是", "或者",
        }

        out = []
        seen = set()
        for item in raw:
            s = item.strip()
            if len(s) <= 1:
                continue
            if s in deny:
                continue
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

# === SANHUA_PROMPT_SLIM_PATCH_V2_BEGIN ===

def _sanhua_split_prompt_blocks(text):
    lines = str(text or "").splitlines()
    blocks = []
    current_title = ""
    current_lines = []

    def flush():
        nonlocal current_title, current_lines
        if current_title or current_lines:
            blocks.append((current_title, current_lines[:]))
        current_title = ""
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            flush()
            current_title = stripped
            current_lines = [line]
        else:
            current_lines.append(line)

    flush()
    return blocks


def _sanhua_join_prompt_blocks(blocks):
    out = []
    for _, lines in blocks:
        chunk = "\n".join(lines).strip()
        if chunk:
            out.append(chunk)
    return "\n\n".join(out).strip()


def _sanhua_dedupe_summary_block(lines):
    if not lines:
        return lines

    kept = [lines[0]]
    seen = set()

    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue

        if s.startswith("- "):
            if s in seen:
                continue
            seen.add(s)

        kept.append(line)

    return kept


def _sanhua_slim_user_profile_block(lines, has_identity_anchor):
    if not lines:
        return lines

    if not has_identity_anchor:
        return lines

    kept = [lines[0]]

    redundant_prefixes = [
        "- 名字:",
        "- 别名:",
        "- 回答风格偏好:",
        "- 响应偏好.",
        "- 当前项目焦点:",
        "- 稳定事实.",
        "- 备注:",
    ]

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        if any(stripped.startswith(prefix) for prefix in redundant_prefixes):
            continue

        kept.append(line)

    if len(kept) <= 1:
        return []

    return kept


def _sanhua_slim_prompt_text(self, text):
    raw = str(text or "").strip()
    if not raw:
        return raw

    blocks = _sanhua_split_prompt_blocks(raw)
    if not blocks:
        return raw

    has_identity_anchor = any(title == "[身份锚点]" for title, _ in blocks)

    slimmed = []
    for title, lines in blocks:
        if title == "[用户画像]":
            lines = _sanhua_slim_user_profile_block(lines, has_identity_anchor)
            if not lines:
                continue
        elif title == "[会话摘要]":
            lines = _sanhua_dedupe_summary_block(lines)

        slimmed.append((title, lines))

    return _sanhua_join_prompt_blocks(slimmed)


if "PromptMemoryBridge" in globals():
    _SANHUA_BRIDGE_CLS = PromptMemoryBridge

    if not hasattr(_SANHUA_BRIDGE_CLS, "_slim_prompt_text"):
        setattr(_SANHUA_BRIDGE_CLS, "_slim_prompt_text", _sanhua_slim_prompt_text)

    _orig_build_prompt = getattr(_SANHUA_BRIDGE_CLS, "build_prompt", None)
    if callable(_orig_build_prompt) and not getattr(_orig_build_prompt, "__sanhua_slim_wrapped__", False):
        def _wrapped_build_prompt(self, *args, **kwargs):
            result = _orig_build_prompt(self, *args, **kwargs)
            if isinstance(result, str):
                return self._slim_prompt_text(result)
            return result

        _wrapped_build_prompt.__sanhua_slim_wrapped__ = True
        setattr(_SANHUA_BRIDGE_CLS, "build_prompt", _wrapped_build_prompt)

    _orig_build_prompt_payload = getattr(_SANHUA_BRIDGE_CLS, "build_prompt_payload", None)
    if callable(_orig_build_prompt_payload) and not getattr(_orig_build_prompt_payload, "__sanhua_slim_wrapped__", False):
        def _wrapped_build_prompt_payload(self, *args, **kwargs):
            payload = _orig_build_prompt_payload(self, *args, **kwargs)
            if isinstance(payload, dict):
                final_prompt = payload.get("final_prompt")
                if isinstance(final_prompt, str):
                    payload = dict(payload)
                    payload["final_prompt"] = self._slim_prompt_text(final_prompt)
            return payload

        _wrapped_build_prompt_payload.__sanhua_slim_wrapped__ = True
        setattr(_SANHUA_BRIDGE_CLS, "build_prompt_payload", _wrapped_build_prompt_payload)

# === SANHUA_PROMPT_SLIM_PATCH_V2_END ===