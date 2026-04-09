#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import py_compile
import shutil
from datetime import datetime
from pathlib import Path


PATCH_MARKER_START = "# === SANHUA_GUI_DISPLAY_SANITIZE_LOCAL_MEMORY_V1_START ==="
PATCH_MARKER_END = "# === SANHUA_GUI_DISPLAY_SANITIZE_LOCAL_MEMORY_V1_END ==="


HELPER_BLOCK = r'''
# === SANHUA_GUI_DISPLAY_SANITIZE_LOCAL_MEMORY_V1_START ===

_SANHUA_GUI_LOCAL_IDENTITY_HINTS = (
    "我是谁",
    "你记得我吗",
    "记得我吗",
    "你认识我吗",
    "我叫什么",
    "我的名字",
)

_SANHUA_GUI_LOCAL_RECALL_HINTS = (
    "帮我回忆刚才我说了什么",
    "刚才我说了什么",
    "我刚才说了什么",
    "回忆刚才",
    "回忆一下",
    "你记得刚才我说了什么",
)

def _sanhua_gui_display_is_polluted(_text):
    _text = str(_text or "").strip()
    if not _text:
        return False

    _markers = (
        "请把下面这些系统记忆当作高优先级参考事实",
        "当前用户问题：",
        "【稳定身份记忆】",
        "【最近会话】",
        "【相关记忆命中】",
        "FAKE_AICORE_REPLY::",
    )
    return any(_m in _text for _m in _markers)


def _sanhua_gui_local_memory_identity_reply(_identity):
    if not isinstance(_identity, dict):
        return ""

    _name = str(_identity.get("name") or "").strip()
    _aliases = [str(x).strip() for x in (_identity.get("aliases") or []) if str(x).strip()]
    _project_focus = [str(x).strip() for x in (_identity.get("project_focus") or []) if str(x).strip()]
    _notes = str(_identity.get("notes") or "").strip()
    _stable_facts = _identity.get("stable_facts") or {}

    _parts = []
    if _name:
        _parts.append(f"你是{_name}。")
    if _aliases:
        _parts.append(f"我记得你的别名有：{', '.join(_aliases)}。")
    if _project_focus:
        _parts.append(f"你当前重点在：{', '.join(_project_focus[:4])}。")
    if _notes:
        _parts.append(_notes)

    _primary_project = str(_stable_facts.get("system.primary_project") or "").strip()
    if _primary_project:
        _parts.append(f"你的核心项目是《{_primary_project}》。")

    _preference = str(_stable_facts.get("response.preference") or "").strip()
    if _preference:
        _parts.append(f"你的偏好是：{_preference}。")

    return "".join(_parts).strip()


def _sanhua_gui_local_memory_recent_reply(_recent, _current_user_text):
    _current_user_text = str(_current_user_text or "").strip()
    _user_msgs = []

    for _m in (_recent or []):
        if not isinstance(_m, dict):
            continue
        if str(_m.get("role") or "").strip() != "user":
            continue
        _content = str(_m.get("content") or "").strip()
        if not _content:
            continue
        if _content == _current_user_text:
            continue
        _user_msgs.append(_content)

    if not _user_msgs:
        return ""

    _user_msgs = _user_msgs[-3:]
    _lines = [f"{idx}. {txt}" for idx, txt in enumerate(_user_msgs, start=1)]
    return "你刚才说过：\n" + "\n".join(_lines)


def _sanhua_gui_try_local_memory_answer(_aicore, _user_text):
    _plain = str(_user_text or "").strip()
    if not _plain:
        return {"ok": False, "reason": "empty_user_text"}

    try:
        _ctx = _sanhua_gui_mem_collect_context(_aicore, _plain, _limit=8)
    except Exception as _e:
        return {"ok": False, "reason": f"context_error:{_e}"}

    _identity = (_ctx or {}).get("identity") or {}
    _recent = (_ctx or {}).get("recent_messages") or []

    if any(_hint in _plain for _hint in _SANHUA_GUI_LOCAL_IDENTITY_HINTS):
        _reply = _sanhua_gui_local_memory_identity_reply(_identity)
        if _reply:
            return {"ok": True, "kind": "identity", "reply": _reply}

    if any(_hint in _plain for _hint in _SANHUA_GUI_LOCAL_RECALL_HINTS):
        _reply = _sanhua_gui_local_memory_recent_reply(_recent, _plain)
        if _reply:
            return {"ok": True, "kind": "recent_recall", "reply": _reply}

    return {"ok": False, "reason": "no_local_answer"}


# === SANHUA_GUI_DISPLAY_SANITIZE_LOCAL_MEMORY_V1_END ===
'''.lstrip("\n")


NEW_CHAT_METHOD = r'''
    # === SANHUA_GUI_CHAT_ROUTE_PRIORITY_V1_START ===
    def _chat_via_actions(self, user_text: str) -> str:
        """
        聊天优先级：
        1) AICore.ask/chat（已挂 GUI memory pipeline）
        2) ai.chat
        3) aicore.chat
        4) 本地记忆兜底
        统一做协议清理与展示层污染拦截。
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

        def _remember_local_answer(_reply: str, _kind: str):
            _reply = str(_reply or "").strip()
            _kind = str(_kind or "").strip() or "local"
            if not _reply:
                return

            try:
                _sanhua_gui_mem_append_chat(getattr(self, "ac", None), "assistant", _reply)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_action(
                    getattr(self, "ac", None),
                    f"gui.local_memory.{_kind}",
                    "success",
                    _reply[:200],
                )
            except Exception:
                pass

        def _try_local_memory() -> str:
            try:
                _local = _sanhua_gui_try_local_memory_answer(getattr(self, "ac", None), user_text)
            except Exception as _e:
                self.append_log(f"⚠️ 本地记忆直答失败: {_e}")
                return ""

            if _local.get("ok"):
                _reply = str(_local.get("reply") or "").strip()
                _kind = str(_local.get("kind") or "local").strip()
                if _reply:
                    self.append_log(f"🧠 GUI local memory answer -> {_kind}")
                    _remember_local_answer(_reply, _kind)
                    return _reply
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

        # 1) 优先 AICore（已接 GUI memory pipeline）
        try:
            if getattr(self, "ac", None) is not None:
                for _name in ("ask", "chat"):
                    _fn = getattr(self.ac, _name, None)
                    if not callable(_fn):
                        continue

                    self.append_log(f"🧠 chat route -> AICore.{_name}")
                    _raw = _fn(user_text)
                    reply = self._strip_llm_protocol(_extract_reply(_raw))

                    if reply.strip():
                        if _sanhua_gui_display_is_polluted(reply):
                            self.append_log("🧼 GUI display sanitize -> polluted AICore reply blocked")
                            _local_reply = _try_local_memory()
                            if _local_reply:
                                return _local_reply
                            reply = ""
                        else:
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
                if _sanhua_gui_display_is_polluted(reply):
                    self.append_log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")
                    _local_reply = _try_local_memory()
                    if _local_reply:
                        return _local_reply
                else:
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
                if _sanhua_gui_display_is_polluted(reply):
                    self.append_log("🧼 GUI display sanitize -> polluted action:aicore.chat reply blocked")
                    _local_reply = _try_local_memory()
                    if _local_reply:
                        return _local_reply
                else:
                    return reply
        except Exception as e:
            self.append_log(f"❌ aicore.chat 失败: {e}")

        # 4) 最后一层：本地记忆直答
        _local_reply = _try_local_memory()
        if _local_reply:
            return _local_reply

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
    rel = target.relative_to(root)
    backup = root / "audit_output" / "fix_backups" / ts / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return backup


def replace_method_block(text: str) -> str:
    start_sig = "    def _chat_via_actions(self, user_text: str) -> str:"
    end_sig = "    def handle_user_message(self, text: str):"

    start = text.find(start_sig)
    if start < 0:
        raise RuntimeError("anchor_not_found:_chat_via_actions")

    end = text.find(end_sig, start)
    if end < 0:
        raise RuntimeError("anchor_not_found:handle_user_message")

    return text[:start] + NEW_CHAT_METHOD + "\n" + text[end:]


def insert_helper_block(text: str) -> str:
    if PATCH_MARKER_START in text and PATCH_MARKER_END in text:
        return text

    anchor = "# === SANHUA_GUI_RUNTIME_AICORE_BRIDGE_V1_START ==="
    idx = text.find(anchor)
    if idx < 0:
        anchor = "if __name__ == \"__main__\":"
        idx = text.find(anchor)
        if idx < 0:
            raise RuntimeError("anchor_not_found:runtime_bridge_or_main")

    return text[:idx] + HELPER_BLOCK + "\n\n" + text[idx:]


def build_patched_text(original: str) -> str:
    patched = original
    patched = insert_helper_block(patched)
    patched = replace_method_block(patched)
    return patched


def preview_diff(before: str, after: str, target: Path) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{target} (before)",
            tofile=f"{target} (after)",
            n=3,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("patch_gui_display_sanitize_local_memory_fallback_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target not found")
        return 2

    before = target.read_text(encoding="utf-8")
    after = build_patched_text(before)

    diff = preview_diff(before, after, target)
    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff)
    else:
        print("[INFO] no textual changes (already patched?)")

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        return 0

    backup = make_backup(root, target)
    target.write_text(after, encoding="utf-8")
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")

    try:
        py_compile.compile(str(target), doraise=True)
        print("[OK] 语法检查通过")
    except Exception as e:
        print(f"[ERROR] 语法检查失败: {e}")
        return 3

    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
