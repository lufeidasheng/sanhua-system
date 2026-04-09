#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


BRIDGE_FILE = Path("core/prompt_engine/prompt_memory_bridge.py")
TEST_FILE = Path("tools/test_prompt_slim_profile.py")


METHOD_BLOCK = r'''
    # =========================
    # Prompt slimming helpers
    # =========================

    def _split_prompt_blocks(self, text: str) -> List[tuple[str, List[str]]]:
        lines = str(text or "").splitlines()
        blocks: List[tuple[str, List[str]]] = []
        current_title = ""
        current_lines: List[str] = []

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

    def _join_prompt_blocks(self, blocks: List[tuple[str, List[str]]]) -> str:
        out: List[str] = []
        for _, lines in blocks:
            chunk = "\n".join(lines).strip()
            if chunk:
                out.append(chunk)
        return "\n\n".join(out).strip()

    def _dedupe_summary_block(self, lines: List[str]) -> List[str]:
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

    def _slim_user_profile_block(self, lines: List[str], has_identity_anchor: bool) -> List[str]:
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

        if len(kept) == 1:
            return []

        return kept

    def _slim_prompt_text(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return raw

        blocks = self._split_prompt_blocks(raw)
        if not blocks:
            return raw

        has_identity_anchor = any(title == "[身份锚点]" for title, _ in blocks)

        slimmed: List[tuple[str, List[str]]] = []
        for title, lines in blocks:
            if title == "[用户画像]":
                lines = self._slim_user_profile_block(lines, has_identity_anchor)
                if not lines:
                    continue
            elif title == "[会话摘要]":
                lines = self._dedupe_summary_block(lines)

            slimmed.append((title, lines))

        return self._join_prompt_blocks(slimmed)
'''


TEST_SCRIPT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()
    payload = aicore.build_memory_payload(
        user_input="系统以后怎么记住我是鹏？",
        session_context={"source": "test_prompt_slim_profile"},
    )
    final_prompt = payload.get("final_prompt", "")

    print("=" * 72)
    print("has_identity_anchor")
    print("=" * 72)
    print("[身份锚点]" in final_prompt)

    print()
    print("=" * 72)
    print("has_user_profile")
    print("=" * 72)
    print("[用户画像]" in final_prompt)

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:4000])


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def insert_method_block(source: str) -> str:
    if "def _slim_prompt_text(self, text: str) -> str:" in source:
        return source

    anchor_candidates = [
        "    def _inject_identity_anchor(self, final_prompt: str) -> str:\n",
        "    def build_prompt(\n",
    ]

    for anchor in anchor_candidates:
        idx = source.find(anchor)
        if idx != -1:
            return source[:idx] + METHOD_BLOCK.strip("\n") + "\n\n" + source[idx:]

    raise SystemExit("未找到可插入 prompt slimming helper 的锚点。")


def patch_build_prompt(source: str) -> str:
    target = "        final_prompt = self._inject_identity_anchor(final_prompt)\n"
    replacement = (
        "        final_prompt = self._inject_identity_anchor(final_prompt)\n"
        "        final_prompt = self._slim_prompt_text(final_prompt)\n"
    )

    if "final_prompt = self._slim_prompt_text(final_prompt)" in source:
        return source

    if target not in source:
        raise SystemExit("未找到 build_prompt 的 identity 注入锚点。")

    return source.replace(target, replacement, 1)


def patch_build_prompt_payload(source: str) -> str:
    old = '            "final_prompt": self._inject_identity_anchor(final_prompt),\n'
    new = '            "final_prompt": self._slim_prompt_text(self._inject_identity_anchor(final_prompt)),\n'

    if new in source:
        return source

    if old in source:
        return source.replace(old, new, 1)

    old2 = '            "final_prompt": final_prompt,\n'
    new2 = '            "final_prompt": self._slim_prompt_text(self._inject_identity_anchor(final_prompt)),\n'

    if old2 in source:
        return source.replace(old2, new2, 1)

    raise SystemExit("未找到 build_prompt_payload 的 final_prompt 锚点。")


def write_test_script() -> Path:
    if TEST_FILE.exists():
        bak = backup(TEST_FILE)
    else:
        bak = TEST_FILE.with_name(TEST_FILE.name + ".bak.created")

    TEST_FILE.write_text(TEST_SCRIPT, encoding="utf-8")
    py_compile.compile(str(TEST_FILE), doraise=True)
    return bak


def main() -> None:
    if not BRIDGE_FILE.exists():
        raise SystemExit(f"未找到文件: {BRIDGE_FILE}")

    source = BRIDGE_FILE.read_text(encoding="utf-8")
    bak = backup(BRIDGE_FILE)

    source = insert_method_block(source)
    source = patch_build_prompt(source)
    source = patch_build_prompt_payload(source)

    BRIDGE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(BRIDGE_FILE), doraise=True)

    bak_test = write_test_script()

    print("✅ prompt slim profile patch 完成并通过语法检查")
    print(f"backup_bridge : {bak}")
    print(f"backup_test   : {bak_test}")
    print("下一步运行：")
    print("python3 tools/test_prompt_slim_profile.py")


if __name__ == "__main__":
    main()
