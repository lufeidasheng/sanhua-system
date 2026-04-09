#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path("core/prompt_engine/prompt_memory_bridge.py")

PATCH_BLOCK = r'''
# === SANHUA_RISK_BLOCK_SLIM_V1_BEGIN ===
import re as _sanhua_risk_re


def _sanhua_risk_slim_prompt(final_prompt: str) -> str:
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

    # 命中次数太低时，整块直接移除，减少噪音
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


if "PromptMemoryBridge" in globals():
    _orig_build_prompt_payload = getattr(PromptMemoryBridge, "build_prompt_payload", None)
    if callable(_orig_build_prompt_payload) and not getattr(_orig_build_prompt_payload, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_prompt_payload(self, *args, **kwargs):
            payload = _orig_build_prompt_payload(self, *args, **kwargs)
            if isinstance(payload, dict):
                final_prompt = payload.get("final_prompt", "")
                payload["final_prompt"] = _sanhua_risk_slim_prompt(final_prompt)
            return payload

        _wrapped_build_prompt_payload._sanhua_risk_slim_wrapped = True
        PromptMemoryBridge.build_prompt_payload = _wrapped_build_prompt_payload

    _orig_build_prompt = getattr(PromptMemoryBridge, "build_prompt", None)
    if callable(_orig_build_prompt) and not getattr(_orig_build_prompt, "_sanhua_risk_slim_wrapped", False):
        def _wrapped_build_prompt(self, *args, **kwargs):
            text = _orig_build_prompt(self, *args, **kwargs)
            return _sanhua_risk_slim_prompt(text)

        _wrapped_build_prompt._sanhua_risk_slim_wrapped = True
        PromptMemoryBridge.build_prompt = _wrapped_build_prompt

# === SANHUA_RISK_BLOCK_SLIM_V1_END ===
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到目标文件: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    bak = backup(TARGET)

    begin = "# === SANHUA_RISK_BLOCK_SLIM_V1_BEGIN ==="
    end = "# === SANHUA_RISK_BLOCK_SLIM_V1_END ==="

    if begin in source and end in source:
        s = source.index(begin)
        e = source.index(end) + len(end)
        source = source[:s].rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"
    else:
        source = source.rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"

    TARGET.write_text(source, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ risk block slim v1 patch 完成并通过语法检查")
    print(f"backup: {bak}")
    print("下一步运行：")
    print("python3 tools/test_risk_block_slim.py")


if __name__ == "__main__":
    main()
