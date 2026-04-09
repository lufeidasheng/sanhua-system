#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path("core/aicore/extensible_aicore.py")

PATCH_BLOCK = r'''
# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_BEGIN ===
import json as _sanhua_deg_json
import hashlib as _sanhua_deg_hashlib
from pathlib import Path as _sanhua_deg_Path
from datetime import datetime as _sanhua_deg_datetime, timezone as _sanhua_deg_timezone


def _sanhua_deg_project_root():
    return _sanhua_deg_Path(__file__).resolve().parents[2]


def _sanhua_deg_now_iso():
    return _sanhua_deg_datetime.now(_sanhua_deg_timezone.utc).astimezone().isoformat()


def _sanhua_deg_normalize_query(query):
    q = str(query or "").strip()
    q = " ".join(q.split())
    return q


def _sanhua_deg_excerpt(text, limit=80):
    s = str(text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[:limit] + " ..."


def _sanhua_deg_make_id(norm_query):
    return _sanhua_deg_hashlib.sha256(norm_query.encode("utf-8")).hexdigest()[:16]


def _sanhua_deg_file(self):
    root = _sanhua_deg_project_root()
    return root / "data" / "memory" / "degraded_patterns.json"


def _sanhua_deg_top_n(self):
    return int(getattr(self, "_degraded_patterns_top_n", 20) or 20)


def _sanhua_deg_cooldown_s(self):
    return float(getattr(self, "_degraded_patterns_cooldown_s", 300.0) or 300.0)


def _sanhua_deg_load(self):
    path = _sanhua_deg_file(self)
    if not path.exists():
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    try:
        data = _sanhua_deg_json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    if isinstance(data, list):
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": data
        }

    if not isinstance(data, dict):
        return {
            "version": "1.0",
            "store": "sanhua_degraded_patterns",
            "updated_at": _sanhua_deg_now_iso(),
            "patterns": []
        }

    data.setdefault("version", "1.0")
    data.setdefault("store", "sanhua_degraded_patterns")
    data.setdefault("updated_at", _sanhua_deg_now_iso())
    data.setdefault("patterns", [])

    if not isinstance(data["patterns"], list):
        data["patterns"] = []

    return data


def _sanhua_deg_save(self, data):
    path = _sanhua_deg_file(self)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _sanhua_deg_now_iso()
    path.write_text(
        _sanhua_deg_json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _sanhua_deg_sort_and_trim(self, patterns):
    def _key(x):
        return (
            int(x.get("count", 0)),
            str(x.get("last_seen", "")),
            str(x.get("query_norm", "")),
        )

    ordered = sorted(patterns, key=_key, reverse=True)
    return ordered[:_sanhua_deg_top_n(self)]


def _sanhua_deg_record(self, query, reason="", force=False):
    norm = _sanhua_deg_normalize_query(query)
    if not norm:
        return None

    now_ts = time.time()
    now_iso = _sanhua_deg_now_iso()
    cooldown_s = _sanhua_deg_cooldown_s(self)

    data = _sanhua_deg_load(self)
    patterns = data.get("patterns", [])

    target = None
    for item in patterns:
        if not isinstance(item, dict):
            continue
        item_norm = str(item.get("query_norm", "")).strip()
        if item_norm == norm:
            target = item
            break
        if not item_norm and str(item.get("query_excerpt", "")).strip() == _sanhua_deg_excerpt(norm):
            target = item
            break

    if target is None:
        target = {
            "id": _sanhua_deg_make_id(norm),
            "query_norm": norm,
            "query_excerpt": _sanhua_deg_excerpt(norm),
            "count": 1,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "last_seen_ts": now_ts,
            "last_reason": str(reason or "").strip(),
        }
        patterns.append(target)
    else:
        last_ts = float(target.get("last_seen_ts", 0.0) or 0.0)
        within_cooldown = (now_ts - last_ts) < cooldown_s

        if force or not within_cooldown:
            target["count"] = int(target.get("count", 0) or 0) + 1

        target["last_seen"] = now_iso
        target["last_seen_ts"] = now_ts
        target["last_reason"] = str(reason or "").strip()

        target.setdefault("id", _sanhua_deg_make_id(norm))
        target.setdefault("query_norm", norm)
        target.setdefault("query_excerpt", _sanhua_deg_excerpt(norm))
        target.setdefault("first_seen", now_iso)

    data["patterns"] = _sanhua_deg_sort_and_trim(self, patterns)
    _sanhua_deg_save(self, data)
    return target


def _sanhua_deg_runtime_status(self):
    data = _sanhua_deg_load(self)
    patterns = data.get("patterns", [])

    top_patterns = []
    for item in patterns[:5]:
        if not isinstance(item, dict):
            continue
        top_patterns.append({
            "id": item.get("id", ""),
            "query_excerpt": item.get("query_excerpt", ""),
            "count": int(item.get("count", 0) or 0),
            "last_seen": item.get("last_seen", ""),
            "last_reason": item.get("last_reason", ""),
        })

    return {
        "path": str(_sanhua_deg_file(self)),
        "patterns_count": len(patterns),
        "top_n": _sanhua_deg_top_n(self),
        "cooldown_s": _sanhua_deg_cooldown_s(self),
        "top_patterns": top_patterns,
    }


if "ExtensibleAICore" in globals():
    setattr(ExtensibleAICore, "_degraded_patterns_top_n", 20)
    setattr(ExtensibleAICore, "_degraded_patterns_cooldown_s", 300.0)

    # 统一覆盖，避免旧逻辑重复累加
    setattr(ExtensibleAICore, "_record_degraded_pattern", _sanhua_deg_record)
    setattr(ExtensibleAICore, "record_degraded_pattern", _sanhua_deg_record)
    setattr(ExtensibleAICore, "_degraded_runtime_status", _sanhua_deg_runtime_status)

# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_END ===
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

    begin = "# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_BEGIN ==="
    end = "# === SANHUA_DEGRADED_PATTERNS_HARDENING_V1_END ==="

    if begin in source and end in source:
        s = source.index(begin)
        e = source.index(end) + len(end)
        source = source[:s].rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"
    else:
        source = source.rstrip() + "\n\n" + PATCH_BLOCK.strip() + "\n"

    TARGET.write_text(source, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print("✅ degraded patterns hardening v1 patch 完成并通过语法检查")
    print(f"backup: {bak}")
    print("下一步运行：")
    print("python3 tools/test_degraded_patterns_hardening.py")


if __name__ == "__main__":
    main()
