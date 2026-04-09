#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print("=" * 72)
    print("RUN:", " ".join(cmd))
    print("=" * 72)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="统一执行 memory 维护任务")
    parser.add_argument("--root", default=".", help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    py = sys.executable

    tasks = [
        [py, "tools/fix_memory_versions_and_dedupe.py", "--root", str(root)],
        [py, "tools/fix_session_summary_canonical.py", "--root", str(root)],
        [py, "tools/compact_session_cache_noise.py", "--root", str(root)],
        [py, "tools/consolidate_memory.py", "--root", str(root)],
        [py, "tools/fix_session_summary_canonical.py", "--root", str(root)],
        [py, "tools/compact_session_cache_noise.py", "--root", str(root)],
    ]

    for task in tasks:
        run(task, root)

    print("=" * 72)
    print("memory maintenance 全部完成")
    print("=" * 72)


if __name__ == "__main__":
    main()
