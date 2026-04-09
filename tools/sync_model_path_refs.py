#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "dependencies",
    "llama.cpp", "juyuan_models", "piper-master",
    "ollama_models", "rollback_snapshots", "build",
    "dist", "node_modules",
}

TEXT_SUFFIXES = {
    ".py", ".json", ".yaml", ".yml", ".txt", ".md", ".sh", ".env"
}


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def main() -> None:
    parser = argparse.ArgumentParser(description="同步项目内旧模型路径到新模型路径")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--old", required=True, help="旧模型路径字符串")
    parser.add_argument("--new", required=True, help="新模型路径字符串")
    parser.add_argument("--apply", action="store_true", help="实际写入替换")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    old = args.old
    new = args.new

    hits = []
    backups = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        if old not in text:
            continue

        rel = path.relative_to(root).as_posix()
        count = text.count(old)
        hits.append((path, rel, count))

        if args.apply:
            bak = backup_file(path)
            backups.append(str(bak))
            path.write_text(text.replace(old, new), encoding="utf-8")

    print("=" * 72)
    print("模型路径扫描/同步完成")
    print("=" * 72)
    print(f"root       : {root}")
    print(f"old        : {old}")
    print(f"new        : {new}")
    print(f"apply      : {args.apply}")
    print(f"hit_files   : {len(hits)}")
    print(f"backups     : {len(backups)}")
    print("-" * 72)

    for _, rel, count in hits:
        print(f"- {rel}  (hits={count})")


if __name__ == "__main__":
    main()
