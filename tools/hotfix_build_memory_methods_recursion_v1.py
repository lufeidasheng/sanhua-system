#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path("core/aicore/extensible_aicore.py")

BEGIN = "# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_BEGIN ==="
END = "# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_END ==="

PATCH = r'''
# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_BEGIN ===

def _sanhua_hotfix_build_memory_prompt(self, user_input, session_context=None, system_persona=None, **kwargs):
    """
    热修复：
    直接走 PromptMemoryBridge 原始能力，绕过历史 wrapper 链，避免递归。
    """
    persona_text = system_persona if system_persona is not None else (getattr(self, "system_persona", "") or "")

    try:
        text = self.prompt_memory_bridge.build_prompt(
            user_input=user_input,
            system_persona=persona_text,
            session_context=session_context,
            **kwargs,
        )

        slim_fn = globals().get("_sanhua_slim_risk_block_text")
        if callable(slim_fn):
            try:
                text = slim_fn(text)
            except Exception:
                pass

        return text

    except Exception as e:
        try:
            log.warning("hotfix build_memory_prompt failed, fallback to raw user_input: %s", e)
        except Exception:
            pass
        return str(user_input or "")


def _sanhua_hotfix_build_memory_payload(self, user_input, session_context=None, system_persona=None, **kwargs):
    """
    热修复：
    直接走 PromptMemoryBridge 原始 payload 构建，绕过 build_memory_payload 的历史 wrapper 链。
    """
    persona_text = system_persona if system_persona is not None else (getattr(self, "system_persona", "") or "")

    try:
        payload = self.prompt_memory_bridge.build_prompt_payload(
            user_input=user_input,
            system_persona=persona_text,
            session_context=session_context,
            **kwargs,
        )

        if not isinstance(payload, dict):
            payload = {
                "user_input": str(user_input or ""),
                "final_prompt": str(user_input or ""),
                "memory_context_text": "",
                "selected_long_term_memories": [],
                "error": "bridge returned non-dict payload",
            }

        slim_fn = globals().get("_sanhua_slim_risk_block_text")
        if callable(slim_fn):
            try:
                payload["final_prompt"] = slim_fn(payload.get("final_prompt", ""))
            except Exception:
                pass

        return payload

    except Exception as e:
        try:
            log.warning("hotfix build_memory_payload failed, fallback payload: %s", e)
        except Exception:
            pass
        return {
            "user_input": str(user_input or ""),
            "final_prompt": str(user_input or ""),
            "memory_context_text": "",
            "selected_long_term_memories": [],
            "error": str(e),
        }


if "ExtensibleAICore" in globals():
    ExtensibleAICore.build_memory_prompt = _sanhua_hotfix_build_memory_prompt
    ExtensibleAICore.build_memory_payload = _sanhua_hotfix_build_memory_payload

# === SANHUA_BUILD_MEMORY_METHODS_HOTFIX_V1_END ===
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def remove_old_block(text: str) -> str:
    if BEGIN not in text or END not in text:
        return text

    s = text.index(BEGIN)
    e = text.index(END) + len(END)
    while e < len(text) and text[e] in "\r\n":
        e += 1

    left = text[:s].rstrip()
    right = text[e:].lstrip("\r\n")

    if left and right:
        return left + "\n\n" + right
    return left + right


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到目标文件: {TARGET}")

    bak = backup(TARGET)
    source = TARGET.read_text(encoding="utf-8")

    source = remove_old_block(source)
    source = source.rstrip() + "\n\n" + PATCH.strip() + "\n"

    TARGET.write_text(source, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ build_memory methods recursion hotfix v1 完成并通过语法检查")
    print(f"backup: {bak}")
    print("下一步运行：")
    print("python3 tools/test_build_memory_methods_recursion_v1.py")


if __name__ == "__main__":
    main()
