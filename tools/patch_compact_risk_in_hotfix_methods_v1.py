#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path("core/aicore/extensible_aicore.py")

BEGIN = "# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_BEGIN ==="
END = "# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_END ==="

PATCH = r'''
# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_BEGIN ===
import json as _sanhua_risk_json
from pathlib import Path as _sanhua_risk_Path


def _sanhua_load_degraded_patterns():
    try:
        root = _sanhua_risk_Path(__file__).resolve().parents[2]
        path = root / "data" / "memory" / "degraded_patterns.json"
        if not path.exists():
            return [], str(path)

        data = _sanhua_risk_json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, list):
            return data, str(path)

        if isinstance(data, dict):
            for key in ("patterns", "items", "entries", "data"):
                arr = data.get(key)
                if isinstance(arr, list):
                    return arr, str(path)

        return [], str(path)
    except Exception:
        return [], ""


def _sanhua_norm_text(s):
    return " ".join(str(s or "").strip().split())


def _sanhua_find_degraded_match(query: str):
    q = _sanhua_norm_text(query)
    if not q:
        return None

    patterns, _ = _sanhua_load_degraded_patterns()
    best = None
    best_score = (-1, -1)

    for item in patterns:
        if not isinstance(item, dict):
            continue

        excerpt = _sanhua_norm_text(item.get("query_excerpt", ""))
        if not excerpt:
            continue

        matched = (
            q == excerpt
            or excerpt in q
            or q in excerpt
        )
        if not matched:
            continue

        try:
            count = int(item.get("count", 0))
        except Exception:
            count = 0

        score = (count, len(excerpt))
        if score > best_score:
            best_score = score
            best = item

    return best


def _sanhua_build_compact_risk_block(query: str) -> str:
    item = _sanhua_find_degraded_match(query)
    if not item:
        return ""

    try:
        count = int(item.get("count", 0))
    except Exception:
        count = 0

    # 低于 3 次不注入，避免噪音
    if count < 3:
        return ""

    excerpt = str(item.get("query_excerpt", "")).strip()
    last_seen = str(item.get("last_seen", "")).strip()

    lines = ["[风险提示]"]
    lines.append(f"- 该问题命中过往低可信回答模式（{count}次）。")

    if excerpt:
        lines.append(f"- 命中问题: {excerpt}")

    if last_seen:
        lines.append(f"- 最近命中: {last_seen}")

    lines.append("- 只基于当前真实工程结构回答；无法确认就直接说明信息不足。")
    return "\n" + "\n".join(lines) + "\n"


def _sanhua_inject_compact_risk_block(final_prompt: str, user_input: str) -> str:
    text = str(final_prompt or "")
    if not text.strip():
        return text

    if "[风险提示]" in text or "[风险问题提示]" in text:
        return text

    block = _sanhua_build_compact_risk_block(user_input)
    if not block:
        return text

    marker = "\n[用户当前输入]\n"
    idx = text.find(marker)
    if idx != -1:
        return text[:idx] + block + text[idx:]

    marker2 = "\n[最后要求]\n"
    idx2 = text.find(marker2)
    if idx2 != -1:
        return text[:idx2] + block + text[idx2:]

    return text.rstrip() + "\n" + block


if "ExtensibleAICore" in globals():
    _orig_build_memory_prompt_for_risk = getattr(ExtensibleAICore, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt_for_risk) and not getattr(_orig_build_memory_prompt_for_risk, "_sanhua_compact_risk_wrapped", False):
        def _wrapped_build_memory_prompt_for_risk(self, user_input, *args, **kwargs):
            text = _orig_build_memory_prompt_for_risk(self, user_input, *args, **kwargs)
            return _sanhua_inject_compact_risk_block(text, user_input)

        _wrapped_build_memory_prompt_for_risk._sanhua_compact_risk_wrapped = True
        ExtensibleAICore.build_memory_prompt = _wrapped_build_memory_prompt_for_risk

    _orig_build_memory_payload_for_risk = getattr(ExtensibleAICore, "build_memory_payload", None)
    if callable(_orig_build_memory_payload_for_risk) and not getattr(_orig_build_memory_payload_for_risk, "_sanhua_compact_risk_wrapped", False):
        def _wrapped_build_memory_payload_for_risk(self, user_input, *args, **kwargs):
            payload = _orig_build_memory_payload_for_risk(self, user_input, *args, **kwargs)
            if isinstance(payload, dict):
                payload["final_prompt"] = _sanhua_inject_compact_risk_block(
                    payload.get("final_prompt", ""),
                    user_input,
                )
            return payload

        _wrapped_build_memory_payload_for_risk._sanhua_compact_risk_wrapped = True
        ExtensibleAICore.build_memory_payload = _wrapped_build_memory_payload_for_risk

# === SANHUA_COMPACT_RISK_IN_HOTFIX_V1_END ===
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

    print("✅ compact risk in hotfix methods v1 patch 完成并通过语法检查")
    print(f"backup: {bak}")
    print("下一步运行：")
    print("python3 tools/test_compact_risk_in_hotfix_methods_v1.py")


if __name__ == "__main__":
    main()
