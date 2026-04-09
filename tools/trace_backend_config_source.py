#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.aicore.config import AICoreConfig


ROOT = Path(__file__).resolve().parents[1]


def safe(obj: Any) -> Any:
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except Exception:
        return str(obj)


def dump_env_candidates() -> dict:
    keys = sorted(
        k for k in os.environ.keys()
        if any(x in k.upper() for x in ["AICORE", "MODEL", "LLAMA", "BACKEND", "OLLAMA"])
    )
    return {k: os.environ.get(k, "") for k in keys}


def main() -> None:
    print("=" * 72)
    print("AICore 运行时配置追踪")
    print("=" * 72)
    print(f"project_root: {ROOT}")
    print("-" * 72)

    cfg = AICoreConfig.from_env()

    print("AICoreConfig 对象")
    print("-" * 72)
    print("type:", type(cfg).__name__)
    print("dict:")
    try:
        print(json.dumps(safe(getattr(cfg, "__dict__", {})), ensure_ascii=False, indent=2))
    except Exception as e:
        print("无法直接输出 __dict__:", e)

    print("-" * 72)
    print("active_backends")
    print("-" * 72)
    try:
        active = cfg.get_active_backends()
        print(f"count: {len(active)}")
        for i, b in enumerate(active, 1):
            print(f"[{i}] type={type(b).__name__}")
            print(json.dumps(safe(getattr(b, "__dict__", {})), ensure_ascii=False, indent=2))
    except Exception as e:
        print("get_active_backends() 失败:", e)

    print("-" * 72)
    print("环境变量候选")
    print("-" * 72)
    print(json.dumps(dump_env_candidates(), ensure_ascii=False, indent=2))

    print("-" * 72)
    print("常见配置文件存在性检查")
    print("-" * 72)
    candidates = [
        ROOT / "config.yaml",
        ROOT / "config.py",
        ROOT / "config" / "global.yaml",
        ROOT / "config" / "global_config.yaml",
        ROOT / "config" / "global_config.json",
        ROOT / "config" / "user.yaml",
        ROOT / "config" / "user_config.yaml",
        ROOT / ".env",
    ]
    for p in candidates:
        print(f"{p.relative_to(ROOT) if p.exists() else p.name}: exists={p.exists()}")

    print("=" * 72)


if __name__ == "__main__":
    main()
