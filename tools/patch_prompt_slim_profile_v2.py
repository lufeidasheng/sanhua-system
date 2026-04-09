#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


BRIDGE_FILE = Path("core/prompt_engine/prompt_memory_bridge.py")
TEST_FILE = Path("tools/test_prompt_slim_profile.py")


PATCH_BLOCK = r'''
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
    print("prompt_length")
    print("=" * 72)
    print(len(final_prompt))

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

    begin_marker = "# === SANHUA_PROMPT_SLIM_PATCH_V2_BEGIN ==="
    end_marker = "# === SANHUA_PROMPT_SLIM_PATCH_V2_END ==="

    if begin_marker in source and end_marker in source:
        start = source.index(begin_marker)
        end = source.index(end_marker) + len(end_marker)
        source = source[:start].rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"
    else:
        source = source.rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"

    BRIDGE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(BRIDGE_FILE), doraise=True)

    bak_test = write_test_script()

    print("✅ prompt slim profile v2 patch 完成并通过语法检查")
    print(f"backup_bridge : {bak}")
    print(f"backup_test   : {bak_test}")
    print("下一步运行：")
    print("python3 tools/test_prompt_slim_profile.py")


if __name__ == "__main__":
    main()
