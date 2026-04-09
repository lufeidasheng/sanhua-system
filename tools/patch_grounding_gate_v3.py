#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path


AICORE_FILE = Path("core/aicore/extensible_aicore.py")
DEBUG_FILE = Path("tools/debug_assistant_gate_fast.py")


HELPER_BLOCK = r'''
    def _extract_grounding_features(self, text: str) -> Dict[str, Any]:
        s = str(text or "").strip()

        current_paths = [
            "core/memory_engine/memory_manager.py",
            "core/prompt_engine/prompt_memory_bridge.py",
            "core/aicore/extensible_aicore.py",
            "data/memory/long_term.json",
            "data/memory/persona.json",
            "data/memory/session_cache.json",
            "data/memory/memory_index.json",
        ]

        exact_symbols = [
            "MemoryManager",
            "PromptMemoryBridge",
            "build_memory_prompt",
            "build_memory_payload",
            "record_chat_memory",
            "record_action_memory",
            "add_long_term_memory",
            "memory_snapshot",
            "memory_health",
            "debug_memory_prompt",
            "get_status",
            "chat",
            "build_prompt",
            "build_prompt_payload",
            "health_check",
            "snapshot",
            "get_active_session",
            "set_active_session",
            "append_recent_message",
            "append_recent_action",
        ]

        bad_patterns = [
            re.compile(r"register_memory_callback"),
            re.compile(r"\bsync_memory\s*\("),
            re.compile(r"\bget_memory\s*\("),
            re.compile(r"\bset_memory\s*\("),
            re.compile(r"\bsave_to_long_term\s*\("),
            re.compile(r"\bload_long_term_memory\s*\("),
            re.compile(r"\bcompress_memory\s*\("),
            re.compile(r"\bupdate_identity\s*\("),
            re.compile(r"\bload_user_identity\s*\("),
            re.compile(r"\b_process_request\b"),
            re.compile(r"\bgenerate_response\s*\("),
            re.compile(r"\bregister_.*module\b"),
            re.compile(r"\bmemory service\b", re.IGNORECASE),
            re.compile(r"\bHTTP/gRPC\b", re.IGNORECASE),
            re.compile(r"<think>", re.IGNORECASE),
            re.compile(r"</think>", re.IGNORECASE),
        ]

        generic_patterns = [
            re.compile(r"双向数据通道"),
            re.compile(r"扩展点"),
            re.compile(r"接口桥接"),
            re.compile(r"身份标识字段"),
            re.compile(r"压缩规则"),
            re.compile(r"查询优化检索效率"),
            re.compile(r"定期清理"),
        ]

        path_hits = [p for p in current_paths if p in s]

        symbol_hits = []
        for sym in exact_symbols:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(sym) + r"(?![A-Za-z0-9_])", s):
                symbol_hits.append(sym)

        bad_hits = [p.pattern for p in bad_patterns if p.search(s)]
        generic_hits = [p.pattern for p in generic_patterns if p.search(s)]

        return {
            "text_length": len(s),
            "path_hits": path_hits,
            "symbol_hits": symbol_hits,
            "bad_hits": bad_hits,
            "generic_hits": generic_hits,
            "contains_code_fence": "```" in s,
            "contains_table": ("|" in s and "---" in s),
        }

    def _assistant_grounding_gate(self, text: str) -> tuple[bool, str]:
        s = str(text or "").strip()
        if not s:
            return False, "empty_answer"

        features = self._extract_grounding_features(s)

        if features["bad_hits"]:
            return False, "bad_patterns=" + ",".join(features["bad_hits"])

        # 关键：只提真实文件名但不提真实方法/类名，仍视为不可信
        if not features["symbol_hits"]:
            return False, "missing_exact_symbols"

        # 只要是泛化架构话术，但没有足够真实锚点，也拦
        if features["generic_hits"] and len(features["symbol_hits"]) < 2:
            return False, "generic_without_enough_grounding"

        # 太短的四条口号式建议，默认拦
        if features["text_length"] < 120 and len(features["symbol_hits"]) < 2:
            return False, "too_short_and_ungrounded"

        return True, "ok"
'''


DEBUG_TOOL = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import requests

from core.aicore.aicore import get_aicore_instance


def extract_content(data: dict) -> str:
    choices = data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""

    first = choices[0]
    if not isinstance(first, dict):
        return ""

    msg = first.get("message")
    if isinstance(msg, dict):
        return str(msg.get("content", "") or "")

    return str(first.get("text", "") or "")


def main() -> None:
    query = "现在三花聚顶的记忆层应该怎么接入 AICore？"

    aicore = get_aicore_instance()
    payload = aicore.build_memory_payload(
        user_input=query,
        session_context={"source": "debug_assistant_gate_fast"},
    )

    final_prompt = payload.get("final_prompt", query)
    status = aicore.get_status()
    base_url = status.get("runtime_model_truth", {}).get("base_url", "http://127.0.0.1:8080").rstrip("/")

    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(final_prompt[:4000])

    print()
    print("=" * 72)
    print("请求后端")
    print("=" * 72)

    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        json={
            "model": "local",
            "messages": [{"role": "user", "content": final_prompt}],
            "temperature": 0.2,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    raw = extract_content(data)
    cleaned = aicore._sanitize_llm_output(raw)
    should_store, reason = aicore._assistant_grounding_gate(cleaned)

    features = aicore._extract_grounding_features(cleaned)

    print("=" * 72)
    print("原始模型回复")
    print("=" * 72)
    print(raw)

    print()
    print("=" * 72)
    print("清洗后回复")
    print("=" * 72)
    print(cleaned)

    print()
    print("=" * 72)
    print("门禁判断")
    print("=" * 72)
    print(f"should_store = {should_store}")
    print(f"reason = {reason}")

    print()
    print("=" * 72)
    print("grounding features")
    print("=" * 72)
    print(json.dumps(features, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def patch_aicore() -> Path:
    if not AICORE_FILE.exists():
        raise SystemExit(f"未找到文件: {AICORE_FILE}")

    source = AICORE_FILE.read_text(encoding="utf-8")
    bak = backup(AICORE_FILE)

    anchor = "    # =========================\n    # Core chat"
    if anchor not in source:
        raise SystemExit("未找到 Core chat 锚点，无法注入 grounding helper。")

    if "def _extract_grounding_features" not in source:
        source = source.replace(anchor, HELPER_BLOCK.strip("\n") + "\n\n" + anchor, 1)

    gate_anchor = "            # 记录 assistant 输出（写入记忆前必须是清洗后的）"
    gate_block = '''
            gate_ok, gate_reason = self._assistant_grounding_gate(resp_text)
            if not gate_ok:
                self.record_action_memory(
                    action_name="aicore.chat",
                    status="degraded",
                    result_summary=gate_reason
                )
                preview = (resp_text[:1200] + " ...[truncated]") if len(resp_text) > 1200 else resp_text
                return (
                    "⚠️ 模型给出了不完整或不可信的最终答案，已阻止写入记忆。\\n\\n"
                    "原因: " + gate_reason + "\\n\\n"
                    "以下是截断前内容预览：\\n" + preview
                )

'''
    if gate_anchor not in source:
        raise SystemExit("未找到 assistant 写入锚点，无法注入严格门禁。")

    if "gate_ok, gate_reason = self._assistant_grounding_gate(resp_text)" not in source:
        source = source.replace(gate_anchor, gate_block + gate_anchor, 1)

    AICORE_FILE.write_text(source, encoding="utf-8")
    py_compile.compile(str(AICORE_FILE), doraise=True)
    return bak


def patch_debug_tool() -> Path:
    DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
    bak = backup(DEBUG_FILE) if DEBUG_FILE.exists() else DEBUG_FILE.with_name(DEBUG_FILE.name + ".bak.created")
    DEBUG_FILE.write_text(DEBUG_TOOL, encoding="utf-8")
    py_compile.compile(str(DEBUG_FILE), doraise=True)
    return bak


def main() -> None:
    bak1 = patch_aicore()
    bak2 = patch_debug_tool()

    print("✅ grounding gate v3 patch 完成并通过语法检查")
    print(f"backup_aicore : {bak1}")
    print(f"backup_debug  : {bak2}")
    print("下一步运行：")
    print("python3 tools/debug_assistant_gate_fast.py")
    print("python - <<'PY'")
    print("from core.aicore.aicore import get_aicore_instance")
    print("aicore = get_aicore_instance()")
    print("print(aicore.chat('现在三花聚顶的记忆层应该怎么接入 AICore？'))")
    print("PY")


if __name__ == "__main__":
    main()
