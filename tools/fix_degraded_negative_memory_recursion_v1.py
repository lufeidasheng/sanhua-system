#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


AICORE_FILE = Path("core/aicore/extensible_aicore.py")
BRIDGE_FILE = Path("core/prompt_engine/prompt_memory_bridge.py")
TEST_FILE = Path("tools/test_degraded_negative_memory_v2.py")


AICORE_PATCH = r'''
# === SANHUA_DEGRADED_PATTERN_PATCH_V2_BEGIN ===
from pathlib import Path as _sanhua_Path
import json as _sanhua_json
import hashlib as _sanhua_hashlib
import re as _sanhua_re
from datetime import datetime as _sanhua_datetime


def _sanhua_aicore_project_root():
    return _sanhua_Path(__file__).resolve().parents[2]


def _sanhua_default_degraded_store():
    return {
        "version": "1.0",
        "store": "sanhua_degraded_patterns",
        "updated_at": "",
        "patterns": [],
    }


def _sanhua_normalize_degraded_question(text):
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = _sanhua_re.sub(r"\s+", "", s)
    s = _sanhua_re.sub(r"[\"'`“”‘’$begin:math:display$$end:math:display$$begin:math:text$$end:math:text${}<>:：,，。！？!?\-_/\\\\|]+", "", s)
    return s[:500]


def _sanhua_degraded_patterns_path(self):
    return _sanhua_aicore_project_root() / "data" / "memory" / "degraded_patterns.json"


def _sanhua_load_degraded_patterns(self):
    path = self._degraded_patterns_path()
    if not path.exists():
        return _sanhua_default_degraded_store()

    try:
        data = _sanhua_json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _sanhua_default_degraded_store()
        if "patterns" not in data or not isinstance(data.get("patterns"), list):
            data["patterns"] = []
        return data
    except Exception:
        return _sanhua_default_degraded_store()


def _sanhua_save_degraded_patterns(self, payload):
    path = self._degraded_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["updated_at"] = _sanhua_datetime.now().astimezone().isoformat()
    if "version" not in payload:
        payload["version"] = "1.0"
    if "store" not in payload:
        payload["store"] = "sanhua_degraded_patterns"
    if "patterns" not in payload or not isinstance(payload.get("patterns"), list):
        payload["patterns"] = []
    path.write_text(
        _sanhua_json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sanhua_record_degraded_pattern(self, query, reason=""):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return {}

    payload = self._load_degraded_patterns()
    patterns = payload.setdefault("patterns", [])
    now_iso = _sanhua_datetime.now().astimezone().isoformat()
    query_excerpt = str(query or "").strip()[:160]
    reason_excerpt = str(reason or "").strip()[:300]

    hit = None
    for item in patterns:
        if str(item.get("normalized", "")).strip() == normalized:
            hit = item
            break

    if hit is None:
        hit = {
            "id": _sanhua_hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
            "query_excerpt": query_excerpt,
            "normalized": normalized,
            "count": 0,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "last_reason": reason_excerpt,
            "kind": "degraded_answer",
        }
        patterns.append(hit)

    hit["count"] = int(hit.get("count", 0)) + 1
    hit["last_seen"] = now_iso
    hit["last_reason"] = reason_excerpt
    if query_excerpt:
        hit["query_excerpt"] = query_excerpt

    patterns.sort(
        key=lambda x: (
            -int(x.get("count", 0)),
            str(x.get("last_seen", "")),
        )
    )
    payload["patterns"] = patterns[:200]
    self._save_degraded_patterns(payload)
    return hit


def _sanhua_get_degraded_pattern_matches(self, query, top_k=2):
    normalized = _sanhua_normalize_degraded_question(query)
    if not normalized:
        return []

    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    scored = []

    for item in patterns:
        qn = str(item.get("normalized", "")).strip()
        if not qn:
            continue

        score = 0
        if qn == normalized:
            score = 100
        elif qn in normalized or normalized in qn:
            score = 80

        if score > 0:
            scored.append((score, int(item.get("count", 0)), item))

    scored.sort(key=lambda x: (-x[0], -x[1], str(x[2].get("last_seen", ""))))
    return [item for _, _, item in scored[:max(1, int(top_k))]]


def _sanhua_inject_degraded_risk_block(self, final_prompt, user_input):
    prompt = str(final_prompt or "").strip()
    if not prompt:
        return prompt

    if "[风险问题提示]" in prompt:
        return prompt

    matches = self._get_degraded_pattern_matches(user_input, top_k=2)
    if not matches:
        return prompt

    lines = [
        "[风险问题提示]",
        "- 当前问题命中过往低可信回答模式。",
    ]

    for item in matches:
        excerpt = str(item.get("query_excerpt", "")).strip()
        count = int(item.get("count", 0))
        last_seen = str(item.get("last_seen", "")).strip()

        if excerpt:
            lines.append(f"- 命中问题: {excerpt}")
        if count:
            lines.append(f"- 历史命中次数: {count}")
        if last_seen:
            lines.append(f"- 最近命中时间: {last_seen}")

    lines.append("- 要求: 对此类问题必须更保守，只能基于当前真实工程结构回答；若无法确认，直接说明信息不足，不要编造。")
    risk_block = "\n".join(lines).strip()

    marker = "[用户当前输入]"
    if marker in prompt:
        return prompt.replace(marker, risk_block + "\n\n" + marker, 1)

    return prompt.rstrip() + "\n\n" + risk_block


def _sanhua_degraded_runtime_status(self):
    payload = self._load_degraded_patterns()
    patterns = payload.get("patterns", [])
    top = []
    for item in patterns[:5]:
        top.append({
            "id": item.get("id", ""),
            "query_excerpt": item.get("query_excerpt", ""),
            "count": int(item.get("count", 0)),
            "last_seen": item.get("last_seen", ""),
            "last_reason": item.get("last_reason", ""),
        })

    return {
        "path": str(self._degraded_patterns_path()),
        "patterns_count": len(patterns),
        "top_patterns": top,
    }


if "ExtensibleAICore" in globals():
    _SANHUA_AICORE_CLS = ExtensibleAICore

    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_patterns_path", _sanhua_degraded_patterns_path)
    if not hasattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_load_degraded_patterns", _sanhua_load_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns"):
        setattr(_SANHUA_AICORE_CLS, "_save_degraded_patterns", _sanhua_save_degraded_patterns)
    if not hasattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern"):
        setattr(_SANHUA_AICORE_CLS, "_record_degraded_pattern", _sanhua_record_degraded_pattern)
    if not hasattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches"):
        setattr(_SANHUA_AICORE_CLS, "_get_degraded_pattern_matches", _sanhua_get_degraded_pattern_matches)
    if not hasattr(_SANHUA_AICORE_CLS, "_inject_degraded_risk_block"):
        setattr(_SANHUA_AICORE_CLS, "_inject_degraded_risk_block", _sanhua_inject_degraded_risk_block)
    if not hasattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status"):
        setattr(_SANHUA_AICORE_CLS, "_degraded_runtime_status", _sanhua_degraded_runtime_status)

    _orig_chat = getattr(_SANHUA_AICORE_CLS, "chat", None)
    if callable(_orig_chat) and not getattr(_orig_chat, "__sanhua_degraded_v2_chat_wrapped__", False):
        def _wrapped_chat(self, query, *args, **kwargs):
            resp = _orig_chat(self, query, *args, **kwargs)
            txt = str(resp or "")
            degraded_markers = [
                "⚠️ 模型给出了不完整或不可信的最终答案",
                "⚠️ 模型给出了不完整的最终答案",
            ]
            if any(marker in txt for marker in degraded_markers):
                try:
                    self._record_degraded_pattern(query, txt[:300])
                except Exception as e:
                    try:
                        log.warning("记录 degraded pattern 失败: %s", e)
                    except Exception:
                        pass
            return resp

        _wrapped_chat.__sanhua_degraded_v2_chat_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "chat", _wrapped_chat)

    _orig_build_memory_prompt = getattr(_SANHUA_AICORE_CLS, "build_memory_prompt", None)
    if callable(_orig_build_memory_prompt) and not getattr(_orig_build_memory_prompt, "__sanhua_degraded_v2_prompt_wrapped__", False):
        def _wrapped_build_memory_prompt(self, user_input, *args, **kwargs):
            result = _orig_build_memory_prompt(self, user_input, *args, **kwargs)
            if isinstance(result, str):
                return self._inject_degraded_risk_block(result, user_input)
            return result

        _wrapped_build_memory_prompt.__sanhua_degraded_v2_prompt_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "build_memory_prompt", _wrapped_build_memory_prompt)

    _orig_build_memory_payload = getattr(_SANHUA_AICORE_CLS, "build_memory_payload", None)
    if callable(_orig_build_memory_payload) and not getattr(_orig_build_memory_payload, "__sanhua_degraded_v2_payload_wrapped__", False):
        def _wrapped_build_memory_payload(self, user_input, *args, **kwargs):
            payload = _orig_build_memory_payload(self, user_input, *args, **kwargs)
            if isinstance(payload, dict):
                final_prompt = payload.get("final_prompt")
                if isinstance(final_prompt, str):
                    payload = dict(payload)
                    payload["final_prompt"] = self._inject_degraded_risk_block(final_prompt, user_input)
            return payload

        _wrapped_build_memory_payload.__sanhua_degraded_v2_payload_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "build_memory_payload", _wrapped_build_memory_payload)

    _orig_get_status = getattr(_SANHUA_AICORE_CLS, "get_status", None)
    if callable(_orig_get_status) and not getattr(_orig_get_status, "__sanhua_degraded_v2_status_wrapped__", False):
        def _wrapped_get_status(self, *args, **kwargs):
            status = _orig_get_status(self, *args, **kwargs)
            if isinstance(status, dict):
                status = dict(status)
                try:
                    status["degraded_memory_runtime"] = self._degraded_runtime_status()
                except Exception as e:
                    status["degraded_memory_runtime"] = {"ok": False, "error": str(e)}
            return status

        _wrapped_get_status.__sanhua_degraded_v2_status_wrapped__ = True
        setattr(_SANHUA_AICORE_CLS, "get_status", _wrapped_get_status)

# === SANHUA_DEGRADED_PATTERN_PATCH_V2_END ===
'''


TEST_SCRIPT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    aicore = get_aicore_instance()

    query = "系统以后怎么记住我是鹏？"

    aicore._record_degraded_pattern(query, "test degraded v2 #1")
    aicore._record_degraded_pattern(query, "test degraded v2 #2")

    payload = aicore.build_memory_payload(
        user_input=query,
        session_context={"source": "test_degraded_negative_memory_v2"},
    )

    print("=" * 72)
    print("degraded_memory_runtime")
    print("=" * 72)
    print(aicore.get_status().get("degraded_memory_runtime"))

    print()
    print("=" * 72)
    print("has_risk_block")
    print("=" * 72)
    print("[风险问题提示]" in payload.get("final_prompt", ""))

    print()
    print("=" * 72)
    print("final_prompt preview")
    print("=" * 72)
    print(payload.get("final_prompt", "")[:4000])


if __name__ == "__main__":
    main()
'''


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def replace_or_append_block(path: Path, begin_marker: str, end_marker: str, new_block: str) -> Path:
    source = path.read_text(encoding="utf-8")
    bak = backup(path)

    if begin_marker in source and end_marker in source:
        start = source.index(begin_marker)
        end = source.index(end_marker) + len(end_marker)
        source = source[:start].rstrip() + "\n\n" + new_block.strip() + "\n"
    else:
        source = source.rstrip() + "\n\n" + new_block.strip() + "\n"

    path.write_text(source, encoding="utf-8")
    return bak


def remove_block_if_exists(path: Path, begin_marker: str, end_marker: str) -> Path | None:
    source = path.read_text(encoding="utf-8")
    if begin_marker not in source or end_marker not in source:
        return None

    bak = backup(path)
    start = source.index(begin_marker)
    end = source.index(end_marker) + len(end_marker)
    source = source[:start].rstrip() + "\n"
    source += source[end:].lstrip("\n")
    path.write_text(source, encoding="utf-8")
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
    if not AICORE_FILE.exists():
        raise SystemExit(f"未找到文件: {AICORE_FILE}")
    if not BRIDGE_FILE.exists():
        raise SystemExit(f"未找到文件: {BRIDGE_FILE}")

    removed_bridge_bak = remove_block_if_exists(
        BRIDGE_FILE,
        "# === SANHUA_DEGRADED_RISK_BRIDGE_PATCH_V1_BEGIN ===",
        "# === SANHUA_DEGRADED_RISK_BRIDGE_PATCH_V1_END ===",
    )

    bak_aicore = replace_or_append_block(
        AICORE_FILE,
        "# === SANHUA_DEGRADED_PATTERN_PATCH_V2_BEGIN ===",
        "# === SANHUA_DEGRADED_PATTERN_PATCH_V2_END ===",
        AICORE_PATCH,
    )

    py_compile.compile(str(AICORE_FILE), doraise=True)
    py_compile.compile(str(BRIDGE_FILE), doraise=True)

    bak_test = write_test_script()

    print("✅ degraded negative memory recursion fix v1 完成并通过语法检查")
    print(f"backup_aicore        : {bak_aicore}")
    print(f"removed_bridge_bak   : {removed_bridge_bak}")
    print(f"backup_test          : {bak_test}")
    print("下一步运行：")
    print("python3 tools/test_degraded_negative_memory_v2.py")


if __name__ == "__main__":
    main()
