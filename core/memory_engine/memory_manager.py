#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryManager:
    """
    三花聚顶正式版 MemoryManager

    统一管理：
    - data/memory/long_term.json
    - data/memory/persona.json
    - data/memory/session_cache.json
    - data/memory/memory_index.json

    设计目标：
    1. 只认一套 memory truth source
    2. 原子写入，避免 JSON 被中途写坏
    3. API 尽量简单，方便 AICore / PromptBridge / GUI 直接接
    """

    DEFAULT_LONG_TERM = {
        "version": "1.0",
        "store": "sanhua_long_term_memory",
        "updated_at": "",
        "memories": [],
    }

    DEFAULT_PERSONA = {
        "version": "1.0",
        "store": "sanhua_persona_memory",
        "updated_at": "",
        "persona": {
            "name": "三花聚顶",
            "system_identity": "",
            "style": "",
            "goals": [],
            "constraints": [],
            "preferences": {},
            "traits": [],
            "notes": "",
        },
    }

    DEFAULT_SESSION_CACHE = {
        "version": "1.0",
        "store": "sanhua_session_cache",
        "updated_at": "",
        "active_session": {
            "session_id": "",
            "started_at": "",
            "last_active_at": "",
            "context_summary": "",
            "recent_messages": [],
            "recent_actions": [],
            "ephemeral_memory": [],
        },
        "recent_sessions": [],
    }

    DEFAULT_MEMORY_INDEX = {
        "version": "1.0",
        "store": "sanhua_memory_index",
        "updated_at": "",
        "index": {
            "long_term_ids": [],
            "persona_keys": [
                "name",
                "system_identity",
                "style",
                "goals",
                "constraints",
                "preferences",
                "traits",
                "notes",
            ],
            "session_ids": [],
        },
        "stats": {
            "long_term_count": 0,
            "persona_field_count": 8,
            "recent_session_count": 0,
        },
    }

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        auto_init: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        self.storage_dir = (
            Path(storage_dir).expanduser().resolve()
            if storage_dir
            else self.project_root / "data" / "memory"
        )

        self.long_term_path = self.storage_dir / "long_term.json"
        self.persona_path = self.storage_dir / "persona.json"
        self.session_cache_path = self.storage_dir / "session_cache.json"
        self.memory_index_path = self.storage_dir / "memory_index.json"

        self._lock = threading.RLock()
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        if auto_init:
            self.ensure_store()

    # =========================
    # 基础工具
    # =========================

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _deepcopy(data: Dict[str, Any]) -> Dict[str, Any]:
        return copy.deepcopy(data)

    def _with_updated_at(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cloned = self._deepcopy(data)
        cloned["updated_at"] = self._now_iso()
        return cloned

    def _atomic_write_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)

    def _read_json(self, path: Path, default_data: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return self._with_updated_at(default_data)

        encodings = ("utf-8", "utf-8-sig", "gbk", "latin-1")
        for enc in encodings:
            try:
                raw = path.read_text(encoding=enc)
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue

        self.logger.warning("读取失败，回退默认结构: %s", path)
        return self._with_updated_at(default_data)

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        payload = self._with_updated_at(data)
        self._atomic_write_json(path, payload)

    # =========================
    # 初始化
    # =========================

    def ensure_store(self) -> None:
        with self._lock:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

            if not self.long_term_path.exists():
                self._write_json(self.long_term_path, self.DEFAULT_LONG_TERM)

            if not self.persona_path.exists():
                self._write_json(self.persona_path, self.DEFAULT_PERSONA)

            if not self.session_cache_path.exists():
                self._write_json(self.session_cache_path, self.DEFAULT_SESSION_CACHE)

            if not self.memory_index_path.exists():
                self._write_json(self.memory_index_path, self.DEFAULT_MEMORY_INDEX)

            self.rebuild_index()

    # =========================
    # 原始加载/保存
    # =========================

    def load_long_term(self) -> Dict[str, Any]:
        with self._lock:
            return self._read_json(self.long_term_path, self.DEFAULT_LONG_TERM)

    def save_long_term(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._write_json(self.long_term_path, data)
            self.rebuild_index()

    def load_persona(self) -> Dict[str, Any]:
        with self._lock:
            return self._read_json(self.persona_path, self.DEFAULT_PERSONA)

    def save_persona(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._write_json(self.persona_path, data)
            self.rebuild_index()

    def load_session_cache(self) -> Dict[str, Any]:
        with self._lock:
            return self._read_json(self.session_cache_path, self.DEFAULT_SESSION_CACHE)

    def save_session_cache(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._write_json(self.session_cache_path, data)
            self.rebuild_index()

    def load_memory_index(self) -> Dict[str, Any]:
        with self._lock:
            return self._read_json(self.memory_index_path, self.DEFAULT_MEMORY_INDEX)

    def save_memory_index(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._write_json(self.memory_index_path, data)

    # =========================
    # Persona API
    # =========================

    def get_persona(self) -> Dict[str, Any]:
        return self.load_persona().get("persona", {})

    def update_persona(
        self,
        name: Optional[str] = None,
        system_identity: Optional[str] = None,
        style: Optional[str] = None,
        goals: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        traits: Optional[List[str]] = None,
        notes: Optional[str] = None,
        merge_preferences: bool = True,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_persona()
            persona = data.setdefault("persona", {})

            if name is not None:
                persona["name"] = name
            if system_identity is not None:
                persona["system_identity"] = system_identity
            if style is not None:
                persona["style"] = style
            if goals is not None:
                persona["goals"] = goals
            if constraints is not None:
                persona["constraints"] = constraints
            if traits is not None:
                persona["traits"] = traits
            if notes is not None:
                persona["notes"] = notes

            if preferences is not None:
                if merge_preferences and isinstance(persona.get("preferences"), dict):
                    merged = dict(persona.get("preferences", {}))
                    merged.update(preferences)
                    persona["preferences"] = merged
                else:
                    persona["preferences"] = preferences

            self.save_persona(data)
            return persona

    # =========================
    # 长期记忆 API
    # =========================

    def list_long_term_memories(
        self,
        sort_by: str = "updated_at",
        descending: bool = True,
    ) -> List[Dict[str, Any]]:
        data = self.load_long_term()
        memories = data.get("memories", [])
        if not isinstance(memories, list):
            return []

        def key_func(item: Dict[str, Any]) -> Any:
            return item.get(sort_by, "")

        return sorted(memories, key=key_func, reverse=descending)

    def add_long_term_memory(
        self,
        content: Any,
        memory_type: str = "fact",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_long_term()
            memories = data.setdefault("memories", [])

            new_id = memory_id or str(uuid.uuid4())
            now = self._now_iso()

            item = {
                "id": new_id,
                "type": memory_type,
                "source": "memory_manager",
                "created_at": now,
                "updated_at": now,
                "importance": float(importance),
                "tags": tags or [],
                "content": content,
                "metadata": metadata or {},
            }

            memories.append(item)
            self.save_long_term(data)
            return item

    def get_long_term_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        for item in self.list_long_term_memories():
            if item.get("id") == memory_id:
                return item
        return None

    def update_long_term_memory(
        self,
        memory_id: str,
        content: Optional[Any] = None,
        memory_type: Optional[str] = None,
        importance: Optional[float] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        merge_metadata: bool = True,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self.load_long_term()
            memories = data.get("memories", [])

            for item in memories:
                if item.get("id") != memory_id:
                    continue

                if content is not None:
                    item["content"] = content
                if memory_type is not None:
                    item["type"] = memory_type
                if importance is not None:
                    item["importance"] = float(importance)
                if tags is not None:
                    item["tags"] = tags
                if metadata is not None:
                    if merge_metadata and isinstance(item.get("metadata"), dict):
                        merged = dict(item.get("metadata", {}))
                        merged.update(metadata)
                        item["metadata"] = merged
                    else:
                        item["metadata"] = metadata

                item["updated_at"] = self._now_iso()
                self.save_long_term(data)
                return item

            return None

    def delete_long_term_memory(self, memory_id: str) -> bool:
        with self._lock:
            data = self.load_long_term()
            memories = data.get("memories", [])
            original_len = len(memories)

            data["memories"] = [m for m in memories if m.get("id") != memory_id]

            if len(data["memories"]) == original_len:
                return False

            self.save_long_term(data)
            return True

    def search_long_term_memories(
        self,
        keyword: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for item in self.list_long_term_memories():
            if min_importance is not None and float(item.get("importance", 0.0)) < float(min_importance):
                continue

            if tags:
                item_tags = set(item.get("tags", []) or [])
                if not set(tags).issubset(item_tags):
                    continue

            if keyword:
                haystack = json.dumps(item, ensure_ascii=False)
                if keyword.lower() not in haystack.lower():
                    continue

            results.append(item)

            if len(results) >= limit:
                break

        return results

    # =========================
    # Session API
    # =========================

    def get_active_session(self) -> Dict[str, Any]:
        data = self.load_session_cache()
        return data.get("active_session", {})

    def set_active_session(
        self,
        session_id: str,
        context_summary: str = "",
        started_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            now = self._now_iso()

            data["active_session"] = {
                "session_id": session_id,
                "started_at": started_at or now,
                "last_active_at": now,
                "context_summary": context_summary,
                "recent_messages": [],
                "recent_actions": [],
                "ephemeral_memory": [],
            }

            self.save_session_cache(data)
            return data["active_session"]

    def update_active_session_summary(self, context_summary: str) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            active = data.setdefault("active_session", {})
            active["context_summary"] = context_summary
            active["last_active_at"] = self._now_iso()
            self.save_session_cache(data)
            return active

    def append_recent_message(
        self,
        role: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 30,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            active = data.setdefault("active_session", self.DEFAULT_SESSION_CACHE["active_session"].copy())

            item = {
                "id": str(uuid.uuid4()),
                "role": role,
                "content": content,
                "metadata": metadata or {},
                "timestamp": self._now_iso(),
            }

            messages = active.setdefault("recent_messages", [])
            messages.append(item)
            active["recent_messages"] = messages[-limit:]
            active["last_active_at"] = self._now_iso()

            self.save_session_cache(data)
            return item

    def append_recent_action(
        self,
        action_name: str,
        status: str = "success",
        result_summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 30,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            active = data.setdefault("active_session", self.DEFAULT_SESSION_CACHE["active_session"].copy())

            item = {
                "id": str(uuid.uuid4()),
                "action_name": action_name,
                "status": status,
                "result_summary": result_summary,
                "metadata": metadata or {},
                "timestamp": self._now_iso(),
            }

            actions = active.setdefault("recent_actions", [])
            actions.append(item)
            active["recent_actions"] = actions[-limit:]
            active["last_active_at"] = self._now_iso()

            self.save_session_cache(data)
            return item

    def add_ephemeral_memory(
        self,
        content: Any,
        memory_type: str = "note",
        metadata: Optional[Dict[str, Any]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            active = data.setdefault("active_session", self.DEFAULT_SESSION_CACHE["active_session"].copy())

            item = {
                "id": str(uuid.uuid4()),
                "type": memory_type,
                "content": content,
                "metadata": metadata or {},
                "timestamp": self._now_iso(),
            }

            ephemeral = active.setdefault("ephemeral_memory", [])
            ephemeral.append(item)
            active["ephemeral_memory"] = ephemeral[-limit:]
            active["last_active_at"] = self._now_iso()

            self.save_session_cache(data)
            return item

    def clear_active_session(self) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session_cache()
            data["active_session"] = copy.deepcopy(self.DEFAULT_SESSION_CACHE["active_session"])
            self.save_session_cache(data)
            return data["active_session"]

    def close_active_session(self, archive: bool = True, keep_recent: int = 10) -> None:
        with self._lock:
            data = self.load_session_cache()
            active = data.get("active_session", {})

            if archive and active.get("session_id"):
                recent_sessions = data.setdefault("recent_sessions", [])
                archived = copy.deepcopy(active)
                recent_sessions.append(archived)
                data["recent_sessions"] = recent_sessions[-keep_recent:]

            data["active_session"] = copy.deepcopy(self.DEFAULT_SESSION_CACHE["active_session"])
            self.save_session_cache(data)

    # =========================
    # Index / Snapshot
    # =========================

    def rebuild_index(self) -> Dict[str, Any]:
        with self._lock:
            long_term = self._read_json(self.long_term_path, self.DEFAULT_LONG_TERM)
            persona = self._read_json(self.persona_path, self.DEFAULT_PERSONA)
            session_cache = self._read_json(self.session_cache_path, self.DEFAULT_SESSION_CACHE)

            long_term_ids = []
            for item in long_term.get("memories", []):
                memory_id = item.get("id")
                if memory_id:
                    long_term_ids.append(memory_id)

            persona_keys = list(persona.get("persona", {}).keys())

            session_ids = []
            active_session = session_cache.get("active_session", {})
            if active_session.get("session_id"):
                session_ids.append(active_session["session_id"])

            for sess in session_cache.get("recent_sessions", []):
                sid = sess.get("session_id")
                if sid:
                    session_ids.append(sid)

            index = {
                "version": "1.0",
                "store": "sanhua_memory_index",
                "updated_at": self._now_iso(),
                "index": {
                    "long_term_ids": long_term_ids,
                    "persona_keys": persona_keys,
                    "session_ids": session_ids,
                },
                "stats": {
                    "long_term_count": len(long_term_ids),
                    "persona_field_count": len(persona_keys),
                    "recent_session_count": len(session_cache.get("recent_sessions", [])),
                },
            }

            self._atomic_write_json(self.memory_index_path, index)
            return index

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "long_term": self.load_long_term(),
                "persona": self.load_persona(),
                "session_cache": self.load_session_cache(),
                "memory_index": self.load_memory_index(),
            }

    # =========================
    # 兼容/辅助
    # =========================

    def health_check(self) -> Dict[str, Any]:
        with self._lock:
            status = {
                "ok": True,
                "storage_dir": str(self.storage_dir),
                "files": {
                    "long_term": self.long_term_path.exists(),
                    "persona": self.persona_path.exists(),
                    "session_cache": self.session_cache_path.exists(),
                    "memory_index": self.memory_index_path.exists(),
                },
            }
            status["ok"] = all(status["files"].values())
            return status


if __name__ == "__main__":
    mm = MemoryManager()
    print(json.dumps(mm.snapshot(), ensure_ascii=False, indent=2))