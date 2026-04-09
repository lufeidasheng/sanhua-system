#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
from datetime import datetime
from pathlib import Path


SCRIPT_NAME = "patch_gui_memory_short_circuit_v1"


def hr():
    print("=" * 96)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    out = backup_root / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def compile_check(target: Path, content: str) -> None:
    compile(content, str(target), "exec")


def patch_source(src: str) -> tuple[str, bool]:
    changed = False

    old_block = """        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\\n"
            "1. 只用中文回答\\n"
            "2. 直接给出最终答案\\n"
            "3. 不要输出思考过程\\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\\n"
            "5. 不要包含任何分析、解释或内部思考\\n"
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
            self.append_log(f"❌ AICore 优先链失败: {e}")"""

    new_block = """        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\\n"
            "1. 只用中文回答\\n"
            "2. 直接给出最终答案\\n"
            "3. 不要输出思考过程\\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\\n"
            "5. 不要包含任何分析、解释或内部思考\\n"
            "6. 以纯文本形式输出"
        )

        # 0) 本地记忆短路优先：身份/最近回忆类问题不必先烧模型
        _local_reply = _try_local_memory()
        if _local_reply:
            self.append_log("⚡ chat short-circuit -> local memory")
            return _local_reply

        # 1) 再走 AICore（已接 GUI memory pipeline）
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
            self.append_log(f"❌ AICore 优先链失败: {e}")"""

    if old_block in src:
        src = src.replace(old_block, new_block, 1)
        changed = True

    return src, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    hr()
    print(SCRIPT_NAME)
    hr()
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target not found")
        return 1

    before = read_text(target)
    after, changed = patch_source(before)

    try:
        compile_check(target, after)
    except Exception as e:
        print(f"[ERROR] compile failed: {e}")
        return 1

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"--- {target} (before)",
            tofile=f"+++ {target} (after)",
            n=3,
        )
    )

    print(f"[INFO] changed: {changed}")
    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff)
    else:
        print("[INFO] no diff")

    if not args.apply:
        print("[PREVIEW] 补丁可应用，且语法通过")
        hr()
        return 0

    backup = make_backup(root, target)
    write_text(target, after)
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    hr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
