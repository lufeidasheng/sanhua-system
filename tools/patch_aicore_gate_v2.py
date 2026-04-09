#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path


TARGET = Path("core/aicore/extensible_aicore.py")


NEW_BLOCK = r'''
    # =========================================================
    # output cleaning and gate
    # =========================================================

    def _sanitize_llm_output(self, text: str) -> str:
        if text is None:
            return ""

        s = str(text).strip()
        if not s:
            return ""

        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE)

        final_marker_patterns = [
            r"<\|start\|>assistant<\|channel\|>final<\|message\|>",
            r"<\|channel\|>final<\|message\|>",
        ]
        for pattern in final_marker_patterns:
            m = re.search(pattern, s, flags=re.IGNORECASE)
            if m:
                s = s[m.end():].strip()
                break

        s = re.sub(
            r"<\|channel\|>analysis<\|message\|>.*?(?=(<\|start\|>assistant<\|channel\|>final<\|message\|>|$))",
            "",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )

        s = re.sub(r"<\|[^>]+?\|>", "", s)
        s = re.sub(r"<\|start\|>|<\|end\|>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"^\s*assistant\s*[:：]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n{3,}", "\n\n", s).strip()
        return s

    def _extract_method_like_tokens(self, text: str) -> List[str]:
        if not text:
            return []

        found = set()
        patterns = [
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(`",
        ]

        ignore = {
            "print", "len", "str", "dict", "list", "set", "int", "float",
            "open", "range", "max", "min", "sum", "any", "all",
            "append", "update", "get", "setdefault", "dumps", "loads", "run",
        }

        for pat in patterns:
            for item in re.findall(pat, text):
                if item in ignore:
                    continue
                found.add(item)

        return sorted(found)

    def _extract_path_refs(self, text: str) -> List[str]:
        if not text:
            return []
        pattern = re.compile(r"(?:[A-Za-z0-9_\-]+/)+[A-Za-z0-9_\-]+\.(?:py|json|yaml|yml|md|txt)")
        return sorted(set(pattern.findall(text)))

    def _build_repo_truth_index(self) -> Dict[str, Any]:
        cached = getattr(self, "_repo_truth_cache", None)
        if isinstance(cached, dict):
            return cached

        root = self._project_root()
        excluded = {
            ".git", "__pycache__", ".venv", "venv", "dependencies",
            "llama.cpp", "juyuan_models", "piper-master",
            "ollama_models", "rollback_snapshots", "build",
            "dist", "node_modules",
        }

        path_set = set()
        symbol_set = set()

        for p in root.rglob("*"):
            if not p.is_file():
                continue

            try:
                rel = p.relative_to(root)
            except Exception:
                continue

            if any(part in excluded for part in rel.parts):
                continue

            rel_str = rel.as_posix()
            path_set.add(rel_str)

            if p.suffix.lower() == ".py":
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue

                for name in re.findall(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, flags=re.MULTILINE):
                    symbol_set.add(name)

                for name in re.findall(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.MULTILINE):
                    symbol_set.add(name)

        cache = {"paths": path_set, "symbols": symbol_set}
        self._repo_truth_cache = cache
        return cache

    def _looks_like_internal_reasoning(self, text: str) -> bool:
        if not text:
            return False

        bad_patterns = [
            "<think>",
            "</think>",
            "The user asks:",
            "We need to respond",
            "首先，我需要回顾",
            "接下来，应该建议用户检查",
            "最后，需要给出",
            "根据已有的信息",
            "根据系统人格",
        ]
        return any(p in text for p in bad_patterns)

    def _looks_incomplete_answer(self, text: str) -> bool:
        if not text:
            return True

        stripped = text.strip()

        if stripped.count("```") % 2 == 1:
            return True

        if stripped.endswith(("：", ":", "```python", "```json", "```yaml", "```")):
            return True

        if "实现路径如下" in stripped and len(stripped) < 140:
            return True

        if len(stripped) < 30 and re.search(r"^\d+\.", stripped):
            return True

        return False

    def _contains_known_fake_structures(self, text: str) -> bool:
        if not text:
            return False

        bad_snippets = [
            "src/memory/manager.py",
            "src/aicore/core.py",
            "run_aicore.py",
            "HTTP/gRPC memory service",
            "PromptMemoryBridge(session_id=",
            "build_contextual_prompt",
            "_build_enhanced_prompt",
            "_call_model(",
            "_process_request",
            "get_context(",
            "get_relevant_memories(",
            "load_long_term_memory",
            "_save_long_term_memory",
            "_load_long_term",
            "index_memory(",
            "sync_memory(",
            "user_identity",
            "memory_type='long_term'",
            "threshold=0.75",
            "long_term_shard_",
            "msgpack",
            "LRU缓存",
            "分片存储",
            "序列化格式升级",
            "双向数据通道",
            "扩展模块",
            "增量压缩",
            "检索优化",
            "持久化绑定",
            "长期记忆关联",
            "字段级压缩",
            "分块压缩策略",
            "下游消费者",
            "会话级记忆隔离",
        ]
        if any(x in text for x in bad_snippets):
            return True

        suspicious_methods = {
            "_process_request",
            "get_context",
            "get_relevant_memories",
            "load_long_term_memory",
            "_save_long_term_memory",
            "_load_long_term",
            "index_memory",
            "sync_memory",
            "build_contextual_prompt",
            "_build_enhanced_prompt",
            "_call_model",
            "generate_response",
            "load_user_memory",
            "validate_answer",
            "check_memory_completeness",
            "validate_user",
            "load_user_identity",
            "set_memory",
            "get_memory",
            "save_to_long_term",
            "compress_memory",
            "decompress_data",
            "load_long_term",
            "update_identity",
        }

        detected = set(self._extract_method_like_tokens(text))
        if detected & suspicious_methods:
            return True

        allowed_private = {
            "_sanitize_llm_output",
            "_extract_method_like_tokens",
            "_extract_path_refs",
            "_build_repo_truth_index",
            "_looks_like_internal_reasoning",
            "_looks_incomplete_answer",
            "_contains_known_fake_structures",
            "_should_store_assistant_message",
            "_build_blocked_answer",
            "_run_memory_consolidation",
            "_maybe_auto_consolidate_memory",
            "_ensure_default_session",
            "_project_root",
            "_consolidate_script",
        }

        for token in detected:
            if token.startswith("_") and token not in allowed_private:
                return True

        repo = self._build_repo_truth_index()

        for path_ref in self._extract_path_refs(text):
            if path_ref not in repo["paths"]:
                return True

        allow_symbol_names = {
            "MemoryManager",
            "PromptMemoryBridge",
            "ExtensibleAICore",
            "build_memory_prompt",
            "build_memory_payload",
            "append_recent_message",
            "append_recent_action",
            "add_long_term_memory",
            "snapshot",
            "health_check",
        }

        for token in detected:
            if token in allow_symbol_names:
                continue
            if token not in repo["symbols"]:
                return True

        return False

    def _should_store_assistant_message(self, cleaned_text: str) -> bool:
        if not cleaned_text.strip():
            return False

        if self._looks_like_internal_reasoning(cleaned_text):
            return False

        if self._looks_incomplete_answer(cleaned_text):
            return False

        if self._contains_known_fake_structures(cleaned_text):
            return False

        return True

    def _build_blocked_answer(self, cleaned_text: str) -> str:
        preview = cleaned_text.strip()
        if len(preview) > 700:
            preview = preview[:700].rstrip() + " ...[truncated]"

        return (
            "⚠️ 模型给出了不完整或不可信的最终答案，已阻止写入记忆。\n\n"
            "以下是截断前内容预览：\n"
            f"{preview}"
        )
'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"未找到文件: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_name(TARGET.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(TARGET, backup)

    pattern = re.compile(
        r"(?s)    # =========================================================\n"
        r"    # output cleaning and gate\n"
        r"    # =========================================================\n.*?"
        r"(?=    # =========================================================\n"
        r"    # auto consolidate\n"
        r"    # =========================================================)",
    )

    m = pattern.search(source)
    if not m:
        raise SystemExit("未匹配到 output cleaning and gate 区块，补丁终止。")

    replacement = NEW_BLOCK.strip("\n") + "\n\n"
    patched = source[:m.start()] + replacement + source[m.end():]

    TARGET.write_text(patched, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ patch 完成并通过语法检查")
    print(f"backup: {backup}")


if __name__ == "__main__":
    main()
