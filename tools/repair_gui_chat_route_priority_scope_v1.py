#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import re
import shutil
from datetime import datetime
from pathlib import Path


REPLACEMENT_BLOCK = r'''
    # === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_START ===
    def _chat_via_actions(self, user_text: str) -> str:
        """
        聊天优先级：
        1) AICore.ask/chat（已挂 GUI memory pipeline）
        2) ai.chat
        3) aicore.chat
        统一做协议清理。
        """

        def _extract_reply(_obj) -> str:
            if _obj is None:
                return ""

            if isinstance(_obj, str):
                return _obj

            if isinstance(_obj, dict):
                _data = _obj.get("data")
                if isinstance(_data, dict):
                    for _k in ("reply", "response", "result", "content", "text", "answer", "message"):
                        _v = _data.get(_k)
                        if isinstance(_v, str) and _v.strip():
                            return _v

                for _k in ("reply", "response", "result", "content", "text", "answer", "message"):
                    _v = _obj.get(_k)
                    if isinstance(_v, str) and _v.strip():
                        return _v

            try:
                return str(_obj)
            except Exception:
                return ""

        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\n"
            "1. 只用中文回答\n"
            "2. 直接给出最终答案\n"
            "3. 不要输出思考过程\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\n"
            "5. 不要包含任何分析、解释或内部思考\n"
            "6. 以纯文本形式输出"
        )

        # 1) 优先 AICore（这里会吃到 GUI memory pipeline）
        try:
            if getattr(self, "ac", None) is not None:
                if callable(getattr(self.ac, "ask", None)):
                    self.append_log("🧠 chat route -> AICore.ask")
                    _raw = self.ac.ask(user_text)
                    reply = self._strip_llm_protocol(_extract_reply(_raw))
                    if reply.strip():
                        return reply

                if callable(getattr(self.ac, "chat", None)):
                    self.append_log("🧠 chat route -> AICore.chat")
                    _raw = self.ac.chat(user_text)
                    reply = self._strip_llm_protocol(_extract_reply(_raw))
                    if reply.strip():
                        return reply
        except Exception as e:
            self.append_log(f"❌ AICore 优先链失败: {e}")

        # 2) ai.chat
        try:
            self.append_log("🤖 chat route -> ai.chat")
            res = self._safe_call_action(
                "ai.chat",
                {
                    "query": user_text,
                    "prompt": user_text,
                    "message": user_text,
                    "text": user_text,
                    "system_prompt": system_prompt,
                    "system": system_prompt,
                },
            )
            reply = self._strip_llm_protocol(_extract_reply(res))
            if reply.strip():
                return reply
        except Exception as e:
            self.append_log(f"❌ ai.chat 失败: {e}")

        # 3) aicore.chat action
        try:
            self.append_log("🤖 chat route -> action:aicore.chat")
            res = self._safe_call_action(
                "aicore.chat",
                {
                    "query": user_text,
                    "prompt": user_text,
                    "message": user_text,
                    "text": user_text,
                },
            )
            reply = self._strip_llm_protocol(_extract_reply(res))
            if reply.strip():
                return reply
        except Exception as e:
            self.append_log(f"❌ aicore.chat 失败: {e}")

        return "抱歉，我这次没有拿到有效回复。"

    def _speak_if_enabled(self, text: str):
        if not self.tts_enabled:
            return
        try:
            clean_text = self._strip_llm_protocol(text)
            acts = self._list_actions()
            if any(a.get("name") == "tts.speak" for a in acts):
                self._safe_call_action("tts.speak", {"text": clean_text, "lang": "zh"})
                self.append_log("🔊 [TTS] 已自动播报")
            else:
                self.append_log("⚠️ [TTS] 模块未加载")
        except Exception as e:
            self.append_log(f"❌ TTS 失败：{e}")

    # === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_END ===
'''.lstrip("\n")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = root / "audit_output" / "fix_backups" / ts / target.relative_to(root)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return backup


def patch_source(src: str) -> tuple[str, bool]:
    # 目标：把 _chat_via_actions 到 handle_user_message 之前的整段
    # 修成 MainWindow 类内方法，并恢复 _speak_if_enabled。
    patterns = [
        re.compile(
            r'(?ms)^ {4}(?:# === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_START ===\n)?'
            r'(?:def _chat_via_actions\(self, user_text: str\) -> str:| {4}def _chat_via_actions\(self, user_text: str\) -> str:)'
            r'.*?(?=^ {4}def handle_user_message\(self, text: str\):)'
        ),
        re.compile(
            r'(?ms)^ {4}def _chat_via_actions\(self, user_text: str\) -> str:'
            r'.*?(?=^ {4}def handle_user_message\(self, text: str\):)'
        ),
        re.compile(
            r'(?ms)^def _chat_via_actions\(self, user_text: str\) -> str:'
            r'.*?(?=^ {4}def handle_user_message\(self, text: str\):|^def handle_user_message\(self, text: str\):)'
        ),
    ]

    for pattern in patterns:
        new_src, count = pattern.subn(REPLACEMENT_BLOCK, src, count=1)
        if count:
            return new_src, new_src != src

    raise RuntimeError("patch_range_not_found:_chat_via_actions_to_handle_user_message")


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 GUI 聊天优先路由补丁的作用域问题")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="写入修改")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("repair_gui_chat_route_priority_scope_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 2

    old = target.read_text(encoding="utf-8")
    try:
        new, changed = patch_source(old)
    except Exception as e:
        print(f"[ERROR] patch_failed: {e}")
        return 3

    if not changed:
        print("[INFO] no_change")
        return 0

    diff = "".join(
        difflib.unified_diff(
            old.splitlines(True),
            new.splitlines(True),
            fromfile=str(target) + " (before)",
            tofile=str(target) + " (after-patch)",
        )
    )

    print("[DIFF PREVIEW]")
    print(diff[:16000])

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        return 0

    backup = make_backup(root, target)
    target.write_text(new, encoding="utf-8")

    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
