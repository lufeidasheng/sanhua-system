#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

TZ8 = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ8).isoformat()


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text: str) -> str:
    s = str(text or "").strip()
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.replace("？", "?").replace("！", "!").replace("。", ".")
    return s.strip()


def message_key(msg: Dict[str, Any]) -> Tuple[str, str]:
    role = str(msg.get("role", "")).strip().lower()
    content = normalize_text(msg.get("content", ""))
    return role, content


def compact_messages(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    if not isinstance(messages, list):
        return [], 0

    grouped: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        key = message_key(msg)
        if not key[1]:
            continue
        grouped.setdefault(key, []).append((idx, msg))

    keep_indices = set()

    for key, items in grouped.items():
        if len(items) == 1:
            keep_indices.add(items[0][0])
            continue

        # 保留首次锚点
        keep_indices.add(items[0][0])
        # 保留最新一次
        keep_indices.add(items[-1][0])

    compacted = [msg for idx, msg in enumerate(messages) if idx in keep_indices]
    removed = len(messages) - len(compacted)
    return compacted, removed


def preview_messages(messages: List[Dict[str, Any]], limit: int = 12) -> List[str]:
    out: List[str] = []
    for i, msg in enumerate(messages[:limit], 1):
        role = msg.get("role", "")
        content = str(msg.get("content", "")).replace("\n", " ").strip()
        if len(content) > 80:
            content = content[:80] + " ..."
        out.append(f"[{i}] {role} | {content}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    session_cache = root / "data" / "memory" / "session_cache.json"
    if not session_cache.exists():
        raise SystemExit(f"未找到: {session_cache}")

    bak = backup(session_cache)
    data = load_json(session_cache)

    active = data.setdefault("active_session", {})
    before_messages = active.get("recent_messages", [])
    before_count = len(before_messages) if isinstance(before_messages, list) else 0

    after_messages, removed = compact_messages(before_messages if isinstance(before_messages, list) else [])
    active["recent_messages"] = after_messages
    active["last_active_at"] = now_iso()
    data["updated_at"] = now_iso()

    save_json(session_cache, data)

    print("=" * 72)
    print("recent_messages 锚点/最新压缩完成")
    print("=" * 72)
    print(f"root             : {root}")
    print(f"backup           : {bak}")
    print(f"messages_before  : {before_count}")
    print(f"messages_after   : {len(after_messages)}")
    print(f"messages_removed : {removed}")
    print("-" * 72)
    print("after_message_previews:")
    for line in preview_messages(after_messages):
        print(line)


if __name__ == "__main__":
    main()
