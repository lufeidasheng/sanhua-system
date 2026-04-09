#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple

TZ8 = timezone(timedelta(hours=8))

PREFERRED_ORDER = [
    "用户当前核心关注项目为三花聚顶系统整改。",
    "用户显式强调身份识别与长期用户记忆。",
    "用户关注三花聚顶记忆层与 AICore 的接入方式。",
    "AICore 对模型不完整答案已有门禁拦截。",
]


def now_iso() -> str:
    return datetime.now(TZ8).isoformat()


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


def norm_text(s: str) -> str:
    return " ".join(str(s or "").replace("\n", " ").split()).strip()


def strip_tail_punct(s: str) -> str:
    s = norm_text(s)
    while s.endswith(("；", ";", "。", ".", "!", "！", "?", "？")):
        s = s[:-1].rstrip()
    return s


def ensure_cn_period(s: str) -> str:
    s = strip_tail_punct(s)
    return s + "。" if s else ""


def split_summary(summary: str) -> List[str]:
    raw = norm_text(summary)
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(";", "；").split("；"):
        chunk = ensure_cn_period(chunk)
        if chunk:
            parts.append(chunk)
    return parts


def dedupe_keep_order(parts: List[str]) -> List[str]:
    out = []
    seen = set()
    for p in parts:
        k = strip_tail_punct(p)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(ensure_cn_period(p))
    return out


def reorder_parts(parts: List[str]) -> List[str]:
    parts = dedupe_keep_order(parts)

    def key_of(x: str) -> str:
        return strip_tail_punct(x)

    original_keys = [key_of(x) for x in parts]
    original_map = {key_of(x): ensure_cn_period(x) for x in parts}

    ordered: List[str] = []
    used = set()

    # 先按固定顺序塞入
    for pref in PREFERRED_ORDER:
        pk = key_of(pref)
        for ok in original_keys:
            if ok == pk or pk in ok or ok in pk:
                if ok not in used:
                    ordered.append(ensure_cn_period(pref))
                    used.add(ok)
                break

    # 再把剩余项按原顺序补在后面
    for p in parts:
        k = key_of(p)
        if k not in used:
            ordered.append(ensure_cn_period(p))
            used.add(k)

    return ordered


def build_canonical_summary(summary: str) -> str:
    parts = split_summary(summary)
    parts = reorder_parts(parts)
    return "；".join(parts)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def lock_session_summary(root: Path) -> Tuple[Path, str, str]:
    memory_dir = root / "data" / "memory"
    session_cache = memory_dir / "session_cache.json"
    memory_index = memory_dir / "memory_index.json"

    if not session_cache.exists():
        raise FileNotFoundError(f"未找到: {session_cache}")

    bak = backup(session_cache)
    if memory_index.exists():
        backup(memory_index)

    cache = load_json(session_cache)
    active = cache.setdefault("active_session", {})

    old_summary = str(active.get("context_summary", "") or "")
    new_summary = build_canonical_summary(old_summary)

    active["context_summary"] = new_summary
    active["last_active_at"] = now_iso()
    cache["updated_at"] = now_iso()

    summaries = active.get("session_summaries")
    if isinstance(summaries, list):
        for item in summaries:
            if isinstance(item, dict):
                item["content"] = new_summary
                item["updated_at"] = now_iso()

    save_json(session_cache, cache)
    return bak, old_summary, new_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bak, old_summary, new_summary = lock_session_summary(root)

    print("=" * 72)
    print("session summary 顺序固化完成")
    print("=" * 72)
    print(f"root                 : {root}")
    print(f"backup               : {bak}")
    print("-" * 72)
    print("before_summary:")
    print(old_summary)
    print("-" * 72)
    print("after_summary:")
    print(new_summary)
    print("-" * 72)
    print("preferred_order:")
    for i, line in enumerate(PREFERRED_ORDER, 1):
        print(f"[{i}] {line}")


if __name__ == "__main__":
    main()
