#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import difflib
from pathlib import Path


def replace_class_method(src: str, method_name: str, new_method: str) -> str:
    lines = src.splitlines(keepends=True)

    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"    def {method_name}("):
            start = i
            break

    if start is None:
        raise RuntimeError(f"未找到方法: {method_name}")

    end = None
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.startswith("    def "):
            end = j
            break

    if end is None:
        end = len(lines)

    new_block = new_method.rstrip("\n") + "\n\n"
    return "".join(lines[:start]) + new_block + "".join(lines[end:])


def patch_gui_main(src: str) -> str:
    new_try_load_aliases = r'''
    def _try_load_aliases(self):
        try:
            from pathlib import Path as _Path

            root = _Path(__file__).resolve().parents[2]
            plat = detect_platform_key()
            base = root / "config" / "aliases.yaml"
            plat_file = root / "config" / f"aliases.{plat}.yaml"

            disp = self.dispatcher
            if not disp:
                self.append_log("⚠️ dispatcher 不可用，跳过 aliases 加载")
                return

            def _alias_count(_d):
                for _attr in ("aliases", "_aliases", "alias_map", "_alias_map"):
                    _v = getattr(_d, _attr, None)
                    if isinstance(_v, dict):
                        return len(_v)
                return 0

            existing = _alias_count(disp)

            if getattr(self.ctx, "_aliases_loaded", False) and existing > 0:
                self.append_log(f"🌸 aliases already loaded = {existing} (platform={plat})")
                return

            total = 0
            if base.exists():
                total += int(load_aliases_from_yaml(str(base), disp) or 0)
            if plat_file.exists():
                total += int(load_aliases_from_yaml(str(plat_file), disp) or 0)

            final_count = _alias_count(disp)

            if total > 0 or final_count > 0:
                try:
                    setattr(self.ctx, "_aliases_loaded", True)
                except Exception:
                    pass
                self.append_log(f"🌸 aliases loaded = {max(total, final_count)} (platform={plat})")
            else:
                self.append_log(
                    f"⚠️ aliases 未加载（未找到 {base} 或 {plat_file}，或 loader 返回 0）"
                )

        except Exception as e:
            self.append_log(f"❌ alias 加载失败：{pretty_exc(e)}")
'''.strip("\n")

    new_chat_via_actions = r'''
    def _chat_via_actions(self, user_text: str) -> str:
        """
        聊天优先级：
        0) 本地记忆短路（身份 / 刚才说了什么）
        1) AICore.ask
        2) ai.chat
        3) aicore.chat
        4) 本地记忆兜底
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

        def _remember_turn(_user_text: str, _reply: str, _kind: str):
            _user_text = str(_user_text or "").strip()
            _reply = str(_reply or "").strip()
            _kind = str(_kind or "").strip() or "chat"
            _ac = getattr(self, "ac", None)

            if not _reply:
                return

            def _has_same_last_user() -> bool:
                try:
                    _snapshot = _sanhua_gui_mem_execute(_ac, "memory.snapshot")
                    if not isinstance(_snapshot, dict):
                        return False
                    _snap = _snapshot.get("snapshot") or {}
                    _session = ((_snap.get("session_cache") or {}).get("active_session") or {})
                    _recent = _session.get("recent_messages") or []
                    for _m in reversed(_recent[-8:]):
                        if not isinstance(_m, dict):
                            continue
                        if str(_m.get("role") or "").strip() != "user":
                            continue
                        return str(_m.get("content") or "").strip() == _user_text
                except Exception:
                    return False
                return False

            try:
                if _user_text and not _has_same_last_user():
                    _sanhua_gui_mem_append_chat(_ac, "user", _user_text)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_chat(_ac, "assistant", _reply)
            except Exception:
                pass

            try:
                _sanhua_gui_mem_append_action(
                    _ac,
                    f"gui.route.{_kind}",
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
                    _remember_turn(user_text, _reply, f"local_memory.{_kind}")
                    return _reply
            return ""

        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        # 0) 本地记忆短路优先
        _local_reply = _try_local_memory()
        if _local_reply:
            self.append_log("⚡ chat short-circuit -> local memory")
            return _local_reply

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\n"
            "1. 只用中文回答\n"
            "2. 直接给出最终答案\n"
            "3. 不要输出思考过程\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\n"
            "5. 不要包含任何分析、解释或内部思考\n"
            "6. 以纯文本形式输出"
        )

        # 1) AICore.ask（不再碰 AICore.chat，先止递归）
        try:
            if getattr(self, "ac", None) is not None and callable(getattr(self.ac, "ask", None)):
                self.append_log("🧠 chat route -> AICore.ask")
                _raw = self.ac.ask(user_text)
                reply = self._strip_llm_protocol(_extract_reply(_raw))

                if reply.strip():
                    if _sanhua_gui_display_is_polluted(reply):
                        self.append_log("🧼 GUI display sanitize -> polluted AICore.ask reply blocked")
                        _local_reply = _try_local_memory()
                        if _local_reply:
                            return _local_reply
                    else:
                        return reply
        except Exception as e:
            self.append_log(f"❌ AICore.ask 失败: {e}")

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
                    _remember_turn(user_text, reply, "ai_chat")
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
                    _remember_turn(user_text, reply, "aicore_chat_action")
                    return reply
        except Exception as e:
            self.append_log(f"❌ aicore.chat 失败: {e}")

        # 4) 最后再试一次本地记忆
        _local_reply = _try_local_memory()
        if _local_reply:
            return _local_reply

        return "抱歉，我这次没有拿到有效回复。"
'''.strip("\n")

    out = src
    out = replace_class_method(out, "_try_load_aliases", new_try_load_aliases)
    out = replace_class_method(out, "_chat_via_actions", new_chat_via_actions)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    if not target.exists():
        raise SystemExit(f"目标文件不存在: {target}")

    before = target.read_text(encoding="utf-8")
    after = patch_gui_main(before)

    print("=" * 96)
    print("patch_gui_hotfix_alias_recursion_memory_v2")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if before == after:
        print("[INFO] changed: False")
        print("[INFO] no diff")
        return 0

    print("[INFO] changed: True")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"--- {target} (before)",
            tofile=f"+++ {target} (after)",
        )
    )
    print("[DIFF PREVIEW]")
    print(diff[:12000] if len(diff) > 12000 else diff)

    if args.apply:
        backup_dir = root / "audit_output" / "fix_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / "gui_main.py.bak_hotfix_alias_recursion_memory_v2"
        backup_file.write_text(before, encoding="utf-8")
        target.write_text(after, encoding="utf-8")
        print(f"[BACKUP] {backup_file}")
        print(f"[PATCHED] {target}")
    else:
        print("[PREVIEW] 补丁可应用")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
