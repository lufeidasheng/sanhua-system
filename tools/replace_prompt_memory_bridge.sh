#!/usr/bin/env bash
set -euo pipefail

TARGET="core/prompt_engine/prompt_memory_bridge.py"
BACKUP="${TARGET}.bak.$(date +%Y%m%d_%H%M%S)"

if [[ ! -f "$TARGET" ]]; then
  echo "❌ 未找到目标文件: $TARGET"
  exit 1
fi

cp "$TARGET" "$BACKUP"
echo "==> 已备份到: $BACKUP"

cat > "$TARGET" <<'PY'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class PromptMemoryBridge:
    """
    负责把 MemoryManager 中的人格、会话缓存、长期记忆，拼成给模型的增强 prompt。
    目标：
    - 只注入最有价值的上下文
    - 避免 prompt 过长导致模型只吐 think
    """

    def __init__(self, memory_manager):
        self.memory_manager = memory_manager

    @staticmethod
    def _compact_text(text: Any, limit: int = 200) -> str:
        if text is None:
            return ""
        s = str(text).strip()
        if len(s) <= limit:
            return s
        return s[:limit] + " ...[truncated]"

    @staticmethod
    def _safe_json(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)

    def _select_long_term_memories(self, user_input: str, top_k: int = 3) -> List[Dict[str, Any]]:
        snapshot = self.memory_manager.snapshot()
        long_term = snapshot.get("long_term", {}).get("memories", []) or []

        if not long_term:
            return []

        query = (user_input or "").lower()
        scored = []

        for item in long_term:
            content = str(item.get("content", ""))
            tags = item.get("tags", []) or []
            importance = float(item.get("importance", 0.5))

            score = importance * 10.0

            if query:
                if query in content.lower():
                    score += 10.0

                for tag in tags:
                    if str(tag).lower() in query or query in str(tag).lower():
                        score += 2.0

                # 关键词简单命中
                for token in ["记忆", "memory", "aicore", "三花聚顶", "prompt", "core"]:
                    if token.lower() in query and token.lower() in content.lower():
                        score += 1.0

            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:top_k]]

    def build_prompt_payload(
        self,
        user_input: str,
        system_persona: str = "",
        session_context: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        snapshot = self.memory_manager.snapshot()

        persona_block = snapshot.get("persona", {}).get("persona", {}) or {}
        active_session = snapshot.get("session_cache", {}).get("active_session", {}) or {}

        recent_messages = active_session.get("recent_messages", []) or []
        recent_actions = active_session.get("recent_actions", []) or []

        # 只保留最近 3 条，避免上下文过重
        recent_messages = recent_messages[-3:]
        recent_actions = recent_actions[-3:]

        selected_long_term = self._select_long_term_memories(user_input=user_input, top_k=3)

        parts: List[str] = []

        if system_persona:
            parts.append("[系统人格]\n" + system_persona.strip())

        # 人格档案
        persona_lines: List[str] = []
        if persona_block.get("name"):
            persona_lines.append(f"- 名称: {persona_block.get('name')}")
        if persona_block.get("style"):
            persona_lines.append(f"- 风格: {persona_block.get('style')}")
        if persona_block.get("goals"):
            persona_lines.append(f"- 目标: {'、'.join(persona_block.get('goals', []))}")
        if persona_block.get("traits"):
            persona_lines.append(f"- 特征: {'、'.join(persona_block.get('traits', []))}")
        if persona_block.get("notes"):
            persona_lines.append(f"- 备注: {self._compact_text(persona_block.get('notes'), 160)}")

        if persona_lines:
            parts.append("[记忆人格档案]\n" + "\n".join(persona_lines))

        # 当前会话缓存
        session_lines: List[str] = []
        if active_session.get("session_id"):
            session_lines.append(f"- session_id: {active_session.get('session_id')}")
        if active_session.get("context_summary"):
            session_lines.append(f"- context_summary: {self._compact_text(active_session.get('context_summary'), 120)}")

        if recent_messages:
            session_lines.append("- recent_messages:")
            for m in recent_messages:
                role = m.get("role", "unknown")
                content = self._compact_text(m.get("content", ""), 120)
                session_lines.append(f"  - [{role}] {content}")

        if recent_actions:
            session_lines.append("- recent_actions:")
            for a in recent_actions:
                name = a.get("action_name", "")
                status = a.get("status", "")
                summary = self._compact_text(a.get("result_summary", ""), 100)
                session_lines.append(f"  - {name} | {status} | {summary}")

        if session_lines:
            parts.append("[当前会话缓存]\n" + "\n".join(session_lines))

        # 外部上下文
        if session_context:
            parts.append("[外部会话上下文]\n" + self._safe_json(session_context))

        # 长期记忆
        if selected_long_term:
            memory_lines = []
            for item in selected_long_term:
                memory_lines.append(
                    f"- type={item.get('memory_type', '')} | "
                    f"importance={item.get('importance', '')} | "
                    f"tags={','.join(item.get('tags', []) or [])}"
                )
                memory_lines.append(
                    f"  content: {self._compact_text(item.get('content', ''), 180)}"
                )
            parts.append("[长期相关记忆]\n" + "\n".join(memory_lines))

        # 最终回答契约：非常关键
        parts.append(
            "[输出约束]\n"
            "1. 禁止输出 <think>、思考过程、推理草稿。\n"
            "2. 禁止虚构项目中不存在的路径、模块、文件。\n"
            "3. 只输出最终答案。\n"
            "4. 优先给出基于当前真实工程结构的增量修改建议。\n"
            "5. 如果信息不足，直接说明不足，不要编造。\n"
        )

        parts.append("[用户当前输入]\n" + str(user_input).strip())

        final_prompt = "\n\n".join(parts).strip()

        return {
            "user_input": user_input,
            "final_prompt": final_prompt,
            "memory_context_text": "\n\n".join(parts[:-1]).strip(),
            "selected_long_term_memories": selected_long_term,
        }

    def build_prompt(
        self,
        user_input: str,
        system_persona: str = "",
        session_context: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        payload = self.build_prompt_payload(
            user_input=user_input,
            system_persona=system_persona,
            session_context=session_context,
            **kwargs,
        )
        return payload["final_prompt"]
PY

python3 -m py_compile "$TARGET"
echo "✅ 已替换并通过语法检查: $TARGET"
