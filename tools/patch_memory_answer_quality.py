#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import shutil
import sys


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"未找到可替换片段: {label}")
    return text.replace(old, new, 1)


def patch_prompt_memory_bridge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # 1) 插入去重 helper
    anchor = """    @staticmethod
    def _safe_json(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)
"""
    insert = """    @staticmethod
    def _safe_json(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)

    @staticmethod
    def _dedupe_messages(messages: List[Dict[str, Any]], keep_last: int = 3) -> List[Dict[str, Any]]:
        if not messages:
            return []

        seen = set()
        result: List[Dict[str, Any]] = []

        for item in reversed(messages):
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            key = (role, content)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

        result.reverse()
        return result[-keep_last:]

    @staticmethod
    def _dedupe_actions(actions: List[Dict[str, Any]], keep_last: int = 3) -> List[Dict[str, Any]]:
        if not actions:
            return []

        seen = set()
        result: List[Dict[str, Any]] = []

        for item in reversed(actions):
            key = (
                str(item.get("action_name", "")).strip(),
                str(item.get("status", "")).strip(),
                str(item.get("result_summary", "")).strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

        result.reverse()
        return result[-keep_last:]
"""
    text = replace_once(text, anchor, insert, "插入 _dedupe_messages/_dedupe_actions")

    # 2) 替换 recent_messages / recent_actions 处理
    old_block = """        recent_messages = active_session.get("recent_messages", []) or []
        recent_actions = active_session.get("recent_actions", []) or []

        # 只保留最近 3 条，避免上下文过重
        recent_messages = recent_messages[-3:]
        recent_actions = recent_actions[-3:]
"""
    new_block = """        recent_messages = active_session.get("recent_messages", []) or []
        recent_actions = active_session.get("recent_actions", []) or []

        # 去重 + 只保留最近 3 条，避免上下文过重
        recent_messages = self._dedupe_messages(recent_messages, keep_last=3)
        recent_actions = self._dedupe_actions(recent_actions, keep_last=3)
"""
    text = replace_once(text, old_block, new_block, "替换 recent_messages/recent_actions 处理")

    path.write_text(text, encoding="utf-8")


def patch_extensible_aicore(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # 1) 插入“不完整答案”检测 helper
    anchor = """    def _looks_like_internal_reasoning(self, text: str) -> bool:
        \"""
        判断内容是否像模型内部思考片段，而不是最终可展示答案。
        \"""
        if not text:
            return False

        s = text.strip()
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
            "确保建议符合",
            "可能用户",
            "需要检查",
            "关键点应该是",
        ]
        hits = sum(1 for marker in reasoning_markers if marker in s)
        return hits >= 2
"""
    insert = """    def _looks_like_internal_reasoning(self, text: str) -> bool:
        \"""
        判断内容是否像模型内部思考片段，而不是最终可展示答案。
        \"""
        if not text:
            return False

        s = text.strip()
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
            "确保建议符合",
            "可能用户",
            "需要检查",
            "关键点应该是",
        ]
        hits = sum(1 for marker in reasoning_markers if marker in s)
        return hits >= 2

    def _looks_incomplete_answer(self, text: str) -> bool:
        \"""
        判断是否像“半截最终答案”：
        - 末尾是反引号、冒号、顿号、逗号、左括号
        - 代码块没闭合
        - 明显是句子没说完
        \"""
        if not text:
            return True

        s = str(text).strip()
        if not s:
            return True

        # 未闭合代码块
        if s.count("```") % 2 != 0:
            return True

        # 尾部明显没写完
        bad_endings = ("`", "：", ":", "，", ",", "（", "(", "|", "示例如下", "包括")
        if s.endswith(bad_endings):
            return True

        # 太短又是步骤型说明，通常是被截断
        if len(s) < 260 and ("具体步骤如下" in s or "步骤如下" in s):
            return True

        # 末尾不是正常收束
        normal_endings = ("。", "！", "？", ".", "!", "?", "”", "\"", "）", ")", "]", "】")
        if len(s) >= 80 and not s.endswith(normal_endings):
            return True

        return False
"""
    text = replace_once(text, anchor, insert, "插入 _looks_incomplete_answer")

    # 2) 在 _should_store_assistant_message 里加入 incomplete 拒绝
    old_gate = """        if self._looks_like_internal_reasoning(s):
            return False
"""
    new_gate = """        if self._looks_like_internal_reasoning(s):
            return False

        if self._looks_incomplete_answer(s):
            return False
"""
    text = replace_once(text, old_gate, new_gate, "门禁增加 incomplete 拒绝")

    # 3) 在 chat() 里加入“不完整答案”降级返回
    old_chat_block = """            # 注意：这里不再把原始 think 文本兜底返回
            if not resp_text.strip():
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary="模型仅返回思考片段或无有效最终答案",
                )
                return "⚠️ 模型只返回了思考片段，没有产出可展示答案。建议减小上下文、提高 max_tokens，或切换更稳的模型。"

            if self._should_store_assistant_message(resp_text):
                self.record_chat_memory("assistant", resp_text)
            else:
                log.info("assistant 输出未写入记忆：质量门禁未通过")
"""
    new_chat_block = """            # 注意：这里不再把原始 think 文本兜底返回
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
                    "⚠️ 模型给出了不完整的最终答案，已阻止写入记忆。\\n\\n"
                    "以下是截断前内容预览：\\n"
                    f"{self._truncate_text(resp_text, 400)}"
                )

            if self._should_store_assistant_message(resp_text):
                self.record_chat_memory("assistant", resp_text)
            else:
                log.info("assistant 输出未写入记忆：质量门禁未通过")
"""
    text = replace_once(text, old_chat_block, new_chat_block, "chat 增加 incomplete 处理")

    path.write_text(text, encoding="utf-8")


def patch_debug_script(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '"max_tokens": 512,',
        '"max_tokens": 1024,',
        "debug_assistant_gate_fast.py 提高 max_tokens",
    )

    text = replace_once(
        text,
        '          "直接给最终答案。"\n',
        '          "直接给最终答案。"\n'
        '          "最终答案控制在 4 条以内，每条尽量短，避免冗长铺垫。"\n',
        "debug_assistant_gate_fast.py 增加简短输出约束",
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = Path(".")

    bridge = root / "core/prompt_engine/prompt_memory_bridge.py"
    aicore = root / "core/aicore/extensible_aicore.py"
    debug = root / "tools/debug_assistant_gate_fast.py"

    for p in [bridge, aicore, debug]:
        if not p.exists():
            print(f"❌ 未找到文件: {p}")
            sys.exit(1)

    print("==> 开始备份")
    for p in [bridge, aicore, debug]:
        bak = backup_file(p)
        print(f"   backup: {bak}")

    print("==> 打补丁")
    patch_prompt_memory_bridge(bridge)
    patch_extensible_aicore(aicore)
    patch_debug_script(debug)

    print("==> 语法检查")
    import py_compile
    py_compile.compile(str(bridge), doraise=True)
    py_compile.compile(str(aicore), doraise=True)
    py_compile.compile(str(debug), doraise=True)

    print("✅ 补丁完成")
    print("下一步执行：")
    print("   python3 tools/debug_assistant_gate_fast.py")
    print("   python - <<'PY'")
    print("   from core.aicore.aicore import get_aicore_instance")
    print("   aicore = get_aicore_instance()")
    print("   print(aicore.chat('现在三花聚顶的记忆层应该怎么接入 AICore？'))")
    print("   PY")


if __name__ == "__main__":
    main()
