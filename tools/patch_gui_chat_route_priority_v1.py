#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import shutil
from datetime import datetime
from pathlib import Path


PATCH_START = "# === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_START ==="
PATCH_END = "# === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_END ==="


NEW_METHOD = r'''
# === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_START ===
def _chat_via_actions(self, user_text: str) -> str:
    """
    聊天优先级：
    1) AICore.ask/chat（已挂 GUI memory pipeline）
    2) ai.chat
    3) aicore.chat
    统一做协议清理。
    """
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

    # 1) 优先 AICore（最关键：这里会吃到 GUI memory pipeline）
    try:
        if getattr(self, "ac", None) is not None:
            if callable(getattr(self.ac, "ask", None)):
                self.append_log("🧠 chat route -> AICore.ask")
                reply = self.ac.ask(user_text) or ""
                reply = self._strip_llm_protocol(str(reply))
                if reply.strip():
                    return reply

            if callable(getattr(self.ac, "chat", None)):
                self.append_log("🧠 chat route -> AICore.chat")
                reply = self.ac.chat(user_text) or ""
                reply = self._strip_llm_protocol(str(reply))
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
                "system_prompt": system_prompt,
            },
        )
        if isinstance(res, dict):
            reply = (
                res.get("reply")
                or res.get("response")
                or res.get("result")
                or res.get("content")
                or ""
            )
        else:
            reply = str(res or "")
        reply = self._strip_llm_protocol(str(reply))
        if reply.strip():
            return reply
    except Exception as e:
        self.append_log(f"❌ ai.chat 失败: {e}")

    # 3) aicore.chat action
    try:
        self.append_log("🤖 chat route -> action:aicore.chat")
        res = self._safe_call_action("aicore.chat", {"query": user_text})
        if isinstance(res, dict):
            reply = (
                res.get("reply")
                or res.get("response")
                or res.get("result")
                or res.get("content")
                or ""
            )
        else:
            reply = str(res or "")
        reply = self._strip_llm_protocol(str(reply))
        if reply.strip():
            return reply
    except Exception as e:
        self.append_log(f"❌ aicore.chat 失败: {e}")

    return "抱歉，我这次没有拿到有效回复。"
# === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_END ===
'''.lstrip("\n")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = root / "audit_output" / "fix_backups" / ts / target.relative_to(root)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return backup


def replace_method(src: str) -> tuple[str, bool]:
    anchor = "def _chat_via_actions(self, user_text: str) -> str:"
    start = src.find(anchor)
    if start < 0:
        raise RuntimeError("anchor_not_found:_chat_via_actions")

    next_anchor = "\n    def handle_user_message(self, text: str):"
    end = src.find(next_anchor, start)
    if end < 0:
        raise RuntimeError("end_anchor_not_found:handle_user_message")

    before = src[:start]
    after = src[end:]

    # 清掉旧 patch 痕迹
    while PATCH_START in before or PATCH_END in before or PATCH_START in after or PATCH_END in after:
        before = before.replace(PATCH_START, "")
        before = before.replace(PATCH_END, "")
        after = after.replace(PATCH_START, "")
        after = after.replace(PATCH_END, "")

    new_src = before + NEW_METHOD + "\n" + after.lstrip("\n")
    return new_src, (new_src != src)


def main() -> int:
    parser = argparse.ArgumentParser(description="修正 GUI 聊天优先路由，优先走 AICore memory pipeline")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("patch_gui_chat_route_priority_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 2

    old = target.read_text(encoding="utf-8")
    new, changed = replace_method(old)

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
    print(diff[:12000])

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
