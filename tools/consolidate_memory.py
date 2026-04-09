#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import uuid
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


@dataclass
class MemoryPaths:
    root: Path
    memory_dir: Path
    long_term: Path
    persona: Path
    session_cache: Path
    memory_index: Path


class MemoryConsolidator:
    """
    目标：
    1. 把 recent_messages / recent_actions 提炼为 session summary
    2. 从消息中提取稳定候选记忆（姓名、偏好、项目焦点等）
    3. 升级 persona.json -> system_persona + user_profile
    4. 升级 long_term.json 为结构化 facts
    5. 刷新 memory_index.json
    """

    def __init__(self, project_root: Path):
        self.paths = MemoryPaths(
            root=project_root,
            memory_dir=project_root / "data" / "memory",
            long_term=project_root / "data" / "memory" / "long_term.json",
            persona=project_root / "data" / "memory" / "persona.json",
            session_cache=project_root / "data" / "memory" / "session_cache.json",
            memory_index=project_root / "data" / "memory" / "memory_index.json",
        )

        self.long_term = read_json(self.paths.long_term, {})
        self.persona = read_json(self.paths.persona, {})
        self.session_cache = read_json(self.paths.session_cache, {})
        self.memory_index = read_json(self.paths.memory_index, {})

        self._normalize_all()

    # =========================
    # normalize
    # =========================

    def _normalize_all(self) -> None:
        self._normalize_long_term()
        self._normalize_persona()
        self._normalize_session_cache()
        self._normalize_memory_index()

    def _normalize_long_term(self) -> None:
        if not isinstance(self.long_term, dict):
            self.long_term = {}

        if "version" not in self.long_term:
            self.long_term["version"] = "2.0"
        if "store" not in self.long_term:
            self.long_term["store"] = "sanhua_long_term_memory"
        if "updated_at" not in self.long_term:
            self.long_term["updated_at"] = now_iso()

        old_memories = self.long_term.get("memories", [])
        normalized: List[Dict[str, Any]] = []

        if isinstance(old_memories, list):
            for item in old_memories:
                if not isinstance(item, dict):
                    continue
                normalized.append(self._normalize_long_term_item(item))

        self.long_term["memories"] = normalized

    def _normalize_long_term_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        content = item.get("content")
        key = item.get("key", "")
        value = item.get("value", "")
        memory_type = item.get("type") or item.get("memory_type") or "fact"

        if (not key or value == "") and content and isinstance(content, str):
            key, value = self._guess_key_value_from_content(content, memory_type)

        return {
            "id": item.get("id") or str(uuid.uuid4()),
            "type": memory_type,
            "key": key or "",
            "value": value if value != "" else content or "",
            "content": content or self._compose_content(memory_type, key, value),
            "confidence": float(item.get("confidence", item.get("importance", 0.7))),
            "source": item.get("source", "legacy_import"),
            "tags": item.get("tags", []),
            "updated_at": item.get("updated_at") or item.get("timestamp") or now_iso(),
            "metadata": item.get("metadata", {}),
        }

    def _normalize_persona(self) -> None:
        if not isinstance(self.persona, dict):
            self.persona = {}

        if "version" not in self.persona:
            self.persona["version"] = "2.0"
        if "store" not in self.persona:
            self.persona["store"] = "sanhua_persona_memory"
        if "updated_at" not in self.persona:
            self.persona["updated_at"] = now_iso()

        old_persona = self.persona.get("persona", {}) if isinstance(self.persona.get("persona"), dict) else {}

        self.persona["system_persona"] = {
            "name": old_persona.get("name", "三花聚顶"),
            "system_identity": old_persona.get("system_identity", ""),
            "style": old_persona.get("style", "务实、模块化、系统化"),
            "goals": old_persona.get("goals", []),
            "constraints": old_persona.get("constraints", []),
            "preferences": old_persona.get("preferences", {}),
            "traits": old_persona.get("traits", []),
            "notes": old_persona.get("notes", ""),
        }

        user_profile = self.persona.get("user_profile", {})
        if not isinstance(user_profile, dict):
            user_profile = {}

        self.persona["user_profile"] = {
            "name": user_profile.get("name", ""),
            "aliases": user_profile.get("aliases", []),
            "preferred_style": user_profile.get("preferred_style", []),
            "response_preferences": user_profile.get("response_preferences", {}),
            "project_focus": user_profile.get("project_focus", []),
            "stable_facts": user_profile.get("stable_facts", {}),
            "notes": user_profile.get("notes", ""),
            "updated_at": user_profile.get("updated_at", now_iso()),
        }

        if "persona" in self.persona:
            del self.persona["persona"]

    def _normalize_session_cache(self) -> None:
        if not isinstance(self.session_cache, dict):
            self.session_cache = {}

        if "version" not in self.session_cache:
            self.session_cache["version"] = "2.0"
        if "store" not in self.session_cache:
            self.session_cache["store"] = "sanhua_session_cache"
        if "updated_at" not in self.session_cache:
            self.session_cache["updated_at"] = now_iso()

        active = self.session_cache.get("active_session", {})
        if not isinstance(active, dict):
            active = {}

        active.setdefault("session_id", "")
        active.setdefault("started_at", "")
        active.setdefault("last_active_at", "")
        active.setdefault("context_summary", "")
        active.setdefault("recent_messages", [])
        active.setdefault("recent_actions", [])
        active.setdefault("ephemeral_memory", [])
        active.setdefault("session_summaries", [])

        if not isinstance(active["session_summaries"], list):
            active["session_summaries"] = []

        self.session_cache["active_session"] = active

        recent_sessions = self.session_cache.get("recent_sessions", [])
        if not isinstance(recent_sessions, list):
            recent_sessions = []
        self.session_cache["recent_sessions"] = recent_sessions

    def _normalize_memory_index(self) -> None:
        if not isinstance(self.memory_index, dict):
            self.memory_index = {}

        if "version" not in self.memory_index:
            self.memory_index["version"] = "2.0"
        if "store" not in self.memory_index:
            self.memory_index["store"] = "sanhua_memory_index"
        if "updated_at" not in self.memory_index:
            self.memory_index["updated_at"] = now_iso()

        self.memory_index["index"] = self.memory_index.get("index", {})
        self.memory_index["stats"] = self.memory_index.get("stats", {})

    # =========================
    # summarization
    # =========================

    def build_session_summary(self) -> Dict[str, Any]:
        active = self.session_cache["active_session"]
        messages = active.get("recent_messages", [])[-20:]
        actions = active.get("recent_actions", [])[-10:]

        key_points: List[str] = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = str(msg.get("content", "")).strip()
            if not content:
                continue

            if role == "user":
                if "记忆" in content and "AICore" in content:
                    key_points.append("用户关注三花聚顶记忆层与 AICore 的接入方式。")
                if "一直运行" in content or "长期运行" in content:
                    key_points.append("用户关注系统长期运行下的持续记忆能力。")
                if "我是鹏" in content or "我叫鹏" in content or "鹏" in content:
                    key_points.append("用户显式强调身份识别与长期用户记忆。")
                if any(x in content for x in ["务实", "系统化", "别太水", "高信息密度"]):
                    key_points.append("用户强调回答风格应务实、系统化、高信息密度。")
                if "三花聚顶" in content:
                    key_points.append("用户当前核心关注项目为三花聚顶系统整改。")

        for act in actions:
            if not isinstance(act, dict):
                continue
            name = act.get("action_name", "")
            status = act.get("status", "")
            summary = str(act.get("result_summary", "")).strip()

            if name == "aicore.chat" and status == "degraded":
                key_points.append("AICore 对模型不完整答案已有门禁拦截。")
            if name == "aicore.chat" and status == "success":
                key_points.append("AICore 到本地模型的对话主链可正常调用。")
            if "记忆" in summary or "MemoryManager" in summary:
                key_points.append("记忆层已具备读写与调用基础。")

        key_points = self._uniq_preserve(key_points)

        summary_text = "；".join(key_points) if key_points else "当前会话暂无可提炼的阶段性摘要。"

        summary_item = {
            "id": str(uuid.uuid4()),
            "session_id": active.get("session_id", ""),
            "created_at": now_iso(),
            "summary_points": key_points,
            "summary_text": summary_text,
            "source_message_count": len(messages),
            "source_action_count": len(actions),
        }
        return summary_item

    def append_session_summary(self) -> Dict[str, Any]:
        active = self.session_cache["active_session"]
        summary_item = self.build_session_summary()

        summaries = active.get("session_summaries", [])
        if not isinstance(summaries, list):
            summaries = []

        if summaries and summaries[-1].get("summary_text") == summary_item["summary_text"]:
            return summaries[-1]

        summaries.append(summary_item)
        active["session_summaries"] = summaries[-20:]
        active["context_summary"] = summary_item["summary_text"]
        active["last_active_at"] = now_iso()

        self.session_cache["active_session"] = active
        self.session_cache["updated_at"] = now_iso()
        return summary_item

    # =========================
    # candidate extraction
    # =========================

    def extract_memory_candidates(self) -> List[Dict[str, Any]]:
        active = self.session_cache["active_session"]
        messages = active.get("recent_messages", [])[-50:]
        candidates: List[Dict[str, Any]] = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "user":
                continue

            content = str(msg.get("content", "")).strip()
            if not content:
                continue

            # 1. 用户名/身份
            name = self._extract_user_name(content)
            if name:
                candidates.append(self._make_candidate(
                    type_="identity",
                    key="name",
                    value=name,
                    content=f"用户名字是{name}",
                    confidence=0.99,
                    source="explicit_user_statement",
                    tags=["user", "identity", "name"],
                ))

            # 2. 回答风格偏好
            style_hits = []
            if "务实" in content:
                style_hits.append("务实")
            if "系统化" in content:
                style_hits.append("系统化")
            if "高信息密度" in content:
                style_hits.append("高信息密度")
            if "别太水" in content or "不要太水" in content:
                style_hits.append("避免空话")
            if "完整代码" in content or "全量代码" in content:
                style_hits.append("偏好完整代码")
            if "结论" in content:
                style_hits.append("结论优先")

            for style in self._uniq_preserve(style_hits):
                candidates.append(self._make_candidate(
                    type_="preference",
                    key="preferred_style",
                    value=style,
                    content=f"用户偏好回答风格：{style}",
                    confidence=0.9,
                    source="repeated_or_explicit_preference",
                    tags=["user", "preference", "style"],
                ))

            # 3. 项目焦点
            if "三花聚顶" in content:
                candidates.append(self._make_candidate(
                    type_="project_focus",
                    key="project_focus",
                    value="三花聚顶",
                    content="用户当前核心项目是三花聚顶系统",
                    confidence=0.95,
                    source="explicit_user_statement",
                    tags=["project", "focus", "sanhua"],
                ))

            if "AICore" in content:
                candidates.append(self._make_candidate(
                    type_="project_focus",
                    key="project_focus",
                    value="AICore",
                    content="用户当前重点整改模块涉及 AICore",
                    confidence=0.86,
                    source="conversation_context",
                    tags=["project", "focus", "aicore"],
                ))

            if "MemoryManager" in content or "记忆层" in content:
                candidates.append(self._make_candidate(
                    type_="architecture_fact",
                    key="memory_architecture_focus",
                    value="记忆层与其他 core 共存，并作为独立核心服务存在",
                    content="用户当前关注记忆层与其他 core 共存的架构整理",
                    confidence=0.9,
                    source="conversation_context",
                    tags=["memory", "architecture", "core"],
                ))

        return self._dedupe_candidates(candidates)

    def _extract_user_name(self, content: str) -> str:
        patterns = [
            r"我叫([^\s，。,.！!？?]{1,12})",
            r"我是([^\s，。,.！!？?]{1,12})",
            r"以后叫我([^\s，。,.！!？?]{1,12})",
            r"记住我叫([^\s，。,.！!？?]{1,12})",
        ]
        for p in patterns:
            m = re.search(p, content)
            if m:
                name = m.group(1).strip()
                if len(name) <= 12 and name not in {"用户", "自己", "这个"}:
                    return name
        return ""

    def _make_candidate(
        self,
        type_: str,
        key: str,
        value: Any,
        content: str,
        confidence: float,
        source: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "type": type_,
            "key": key,
            "value": value,
            "content": content,
            "confidence": confidence,
            "source": source,
            "tags": tags or [],
            "updated_at": now_iso(),
            "metadata": {},
        }

    def _dedupe_candidates(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for item in items:
            sig = (item.get("type"), item.get("key"), json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(item)
        return out

    # =========================
    # promotion
    # =========================

    def promote_stable_memories(self) -> Dict[str, Any]:
        candidates = self.extract_memory_candidates()
        promoted = []
        updated_profile_fields = []

        existing = self.long_term.get("memories", [])
        if not isinstance(existing, list):
            existing = []

        existing_map = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            sig = (item.get("type"), item.get("key"), json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True))
            existing_map[sig] = item

        profile = self.persona["user_profile"]

        for cand in candidates:
            sig = (cand.get("type"), cand.get("key"), json.dumps(cand.get("value"), ensure_ascii=False, sort_keys=True))

            if sig not in existing_map:
                existing.append(cand)
                promoted.append(cand)

            ctype = cand.get("type")
            key = cand.get("key")
            value = cand.get("value")

            if ctype == "identity" and key == "name":
                if profile.get("name") != value:
                    profile["name"] = value
                    updated_profile_fields.append("user_profile.name")

            elif ctype == "preference" and key == "preferred_style":
                current = profile.get("preferred_style", [])
                if value not in current:
                    current.append(value)
                    profile["preferred_style"] = current
                    updated_profile_fields.append("user_profile.preferred_style")

            elif ctype == "project_focus" and key == "project_focus":
                current = profile.get("project_focus", [])
                if value not in current:
                    current.append(value)
                    profile["project_focus"] = current
                    updated_profile_fields.append("user_profile.project_focus")

            elif ctype == "architecture_fact":
                facts = profile.get("stable_facts", {})
                facts["memory_architecture_focus"] = value
                profile["stable_facts"] = facts
                updated_profile_fields.append("user_profile.stable_facts.memory_architecture_focus")

        profile["updated_at"] = now_iso()
        self.persona["user_profile"] = profile

        self.long_term["memories"] = existing
        self.long_term["updated_at"] = now_iso()
        self.persona["updated_at"] = now_iso()

        return {
            "candidates_count": len(candidates),
            "promoted_count": len(promoted),
            "promoted_items": promoted,
            "updated_profile_fields": self._uniq_preserve(updated_profile_fields),
        }

    # =========================
    # index refresh
    # =========================

    def refresh_memory_index(self) -> Dict[str, Any]:
        memories = self.long_term.get("memories", [])
        active = self.session_cache.get("active_session", {})
        profile = self.persona.get("user_profile", {})

        long_term_ids = []
        memory_keys = []
        tags = set()

        for item in memories:
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                long_term_ids.append(item["id"])
            if item.get("key"):
                memory_keys.append(item["key"])
            for t in item.get("tags", []):
                tags.add(t)

        session_summaries = active.get("session_summaries", [])
        session_summary_ids = [x.get("id") for x in session_summaries if isinstance(x, dict) and x.get("id")]

        self.memory_index["index"] = {
            "long_term_ids": long_term_ids,
            "memory_keys": sorted(set(memory_keys)),
            "session_summary_ids": session_summary_ids,
            "persona_keys": sorted(profile.keys()),
            "tags": sorted(tags),
        }

        self.memory_index["stats"] = {
            "long_term_count": len(long_term_ids),
            "session_summary_count": len(session_summary_ids),
            "persona_field_count": len(profile.keys()),
            "user_name_present": bool(profile.get("name")),
            "preferred_style_count": len(profile.get("preferred_style", [])),
            "project_focus_count": len(profile.get("project_focus", [])),
        }

        self.memory_index["updated_at"] = now_iso()
        return self.memory_index

    # =========================
    # commit
    # =========================

    def save_all(self) -> None:
        write_json(self.paths.long_term, self.long_term)
        write_json(self.paths.persona, self.persona)
        write_json(self.paths.session_cache, self.session_cache)
        write_json(self.paths.memory_index, self.memory_index)

    def run(self) -> Dict[str, Any]:
        backups = [
            backup_file(self.paths.long_term),
            backup_file(self.paths.persona),
            backup_file(self.paths.session_cache),
            backup_file(self.paths.memory_index),
        ]

        session_summary = self.append_session_summary()
        promote_result = self.promote_stable_memories()
        index_result = self.refresh_memory_index()
        self.save_all()

        return {
            "ok": True,
            "memory_dir": str(self.paths.memory_dir),
            "backups": [str(x) for x in backups if x],
            "session_summary": session_summary,
            "promote_result": promote_result,
            "index_stats": index_result.get("stats", {}),
            "user_profile": self.persona.get("user_profile", {}),
        }

    # =========================
    # helpers
    # =========================

    def _guess_key_value_from_content(self, content: str, memory_type: str) -> Tuple[str, Any]:
        if "名字是" in content:
            m = re.search(r"名字是(.+)$", content)
            if m:
                return "name", m.group(1).strip()
        if memory_type == "project_focus" and "三花聚顶" in content:
            return "project_focus", "三花聚顶"
        return "", content

    def _compose_content(self, memory_type: str, key: str, value: Any) -> str:
        if key and value != "":
            return f"{memory_type}:{key}={value}"
        return str(value)

    def _uniq_preserve(self, items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="三花聚顶记忆压缩、总结、用户画像升级工具")
    parser.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    consolidator = MemoryConsolidator(root)
    result = consolidator.run()

    print("=" * 72)
    print("三花聚顶记忆整合完成")
    print("=" * 72)
    print(f"memory_dir            : {result['memory_dir']}")
    print(f"backups               : {len(result['backups'])}")
    print(f"promoted_count        : {result['promote_result']['promoted_count']}")
    print(f"candidates_count      : {result['promote_result']['candidates_count']}")
    print(f"user_profile.name     : {result['user_profile'].get('name', '')}")
    print(f"user_profile.styles   : {result['user_profile'].get('preferred_style', [])}")
    print(f"user_profile.projects : {result['user_profile'].get('project_focus', [])}")
    print("-" * 72)
    print("session_summary:")
    print(result["session_summary"]["summary_text"])
    print("-" * 72)
    print("index_stats:")
    print(json.dumps(result["index_stats"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
