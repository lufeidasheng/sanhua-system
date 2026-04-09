#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(".")
BRIDGE = ROOT / "core/prompt_engine/prompt_memory_bridge.py"
AICORE = ROOT / "core/aicore/extensible_aicore.py"


OLD_BEGIN = "# === SANHUA_RISK_BLOCK_SLIM_V1_BEGIN ==="
OLD_END = "# === SANHUA_RISK_BLOCK_SLIM_V1_END ==="

NEW_BEGIN = "# === SANHUA_RISK_BLOCK_SLIM_V2_BEGIN ==="
NEW_END = "# === SANHUA_RISK_BLOCK_SLIM_V2_END ==="


AICORE_PATCH = r'''
# === SANHUA_RISK_BLOCK_SLIM_V2_BEGIN ===
import re as _sanhua_risk_re


def _sanhua_slim_risk_block_text(final_prompt: str) -> str:
    text = str(final_prompt or "")
    if not text.strip():
        return text

    pattern = _sanhua_risk_re.compile(
        r"\n\[风险问题提示\]\n(?P<body>.*?)(?=\n\[用户当前输入\]|\n\[最后要求\]|\Z)",
        _sanhua_risk_re.DOTALL,
    )

    m = pattern.search(text)
    if not m:
        return text

    body = m.group("body") or ""

    count = None
    hit_query = ""
    last_seen = ""

    m_count = _sanhua_risk_re.search(r"历史命中次数:\s*(\d+)", body)
    if m_count:
        try:
            count = int(m_count.group(1))
        except Exception:
            count = None

    m_query = _sanhua_risk_re.search(r"命中问题:\s*(.+)", body)
    if m_query:
        hit_query = str(m_query.group(1)).strip()

    m_last = _sanhua_risk_re.search(r"最近命中时间:\s*(.+)", body)
    if m_last:
        last_seen = str(m_last.group(1)).strip()

    # 命中次数太低：整块直接删掉，减少 prompt 噪音
    if count is not None and count < 3:
        return text[:m.start()] + "\n" + text[m.end():]

    compact_lines = ["[风险提示]"]

    if count is not None:
        compact_lines.append(f"- 该问题命中过往低可信回答模式（{count}次）。")
    else:
        compact_lines.append("- 该问题命中过往低可信回答模式。")

    if hit_query:
        compact_lines.append(f"- 命中问题: {hit_query}")

    if last_seen:
        compact_lines.append(f"- 最近命中: {last_seen}")

    compact_lines.append("- 只基于当前真实工程结构回答；无法确认就直接说明信息不足。")

    compact = "\n" + "\n".join(compact_lines) + "\n"
    return text[:m.start()] + compact + text[m.end():]


if "ExtensibleAICore" in globals():
    _orig_build_memory_prompt = getattr(ExtensibleAICore, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt) and not getattr(_orig_build_memory_prompt, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_memory_prompt(self, *args, **kwargs):
            text = _orig_build_memory_prompt(self, *args, **kwargs)
            return _sanhua_slim_risk_block_text(text)

        _wrapped_build_memory_prompt._sanhua_risk_slim_wrapped = True
        ExtensibleAICore.build_memory_prompt = _wrapped_build_memory_prompt

    _orig_build_memory_payload = getattr(ExtensibleAICore, "build_memory_payload", None)
    if callable(_orig_build_memory_payload) and not getattr(_orig_build_memory_payload, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_memory_payload(self, *args, **kwargs):
            payload = _orig_build_memory_payload(self, *args, **kwargs)
            if isinstance(payload, dict):
                payload["final_prompt"] = _sanhua_slim_risk_block_text(payload.get("final_prompt", ""))
            return payload

        _wrapped_build_memory_payload._sanhua_risk_slim_wrapped = True
        ExtensibleAICore.build_memory_payload = _wrapped_build_memory_payload

# === SANHUA_RISK_BLOCK_SLIM_V2_END ===
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def remove_block(text: str, begin: str, end: str) -> str:
    if begin not in text or end not in text:
        return text
    s = text.index(begin)
    e = text.index(end) + len(end)
    while e < len(text) and text[e] in "\r\n":
        e += 1
    left = text[:s].rstrip()
    right = text[e:].lstrip("\r\n")
    if left and right:
        return left + "\n\n" + right
    return left + right


def main() -> None:
    if not BRIDGE.exists():
        raise SystemExit(f"未找到文件: {BRIDGE}")
    if not AICORE.exists():
        raise SystemExit(f"未找到文件: {AICORE}")

    bridge_bak = backup(BRIDGE)
    aicore_bak = backup(AICORE)

    # 1) 先从 PromptMemoryBridge 里移除旧的递归补丁
    bridge_src = BRIDGE.read_text(encoding="utf-8")
    bridge_src = remove_block(bridge_src, OLD_BEGIN, OLD_END)
    BRIDGE.write_text(bridge_src, encoding="utf-8")

    # 2) 再把安全补丁挂到 ExtensibleAICore
    aicore_src = AICORE.read_text(encoding="utf-8")
    aicore_src = remove_block(aicore_src, NEW_BEGIN, NEW_END)
    aicore_src = aicore_src.rstrip() + "\n\n" + AICORE_PATCH.strip() + "\n"
    AICORE.write_text(aicore_src, encoding="utf-8")

    # 3) 语法检查
    py_compile.compile(str(BRIDGE), doraise=True)
    py_compile.compile(str(AICORE), doraise=True)

    print("✅ risk block slim recursion fix v2 完成并通过语法检查")
    print(f"backup_bridge: {bridge_bak}")
    print(f"backup_aicore: {aicore_bak}")
    print("下一步运行：")
    print("python3 tools/test_risk_block_slim_v2.py")


if __name__ == "__main__":
    main()
