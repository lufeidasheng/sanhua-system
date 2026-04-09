#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶系统 · 第二波核心文件打包脚本

作用：
1. 从项目根目录复制第二波指定文件
2. 输出到“第二波”目录
3. 保留原始相对目录结构
4. 生成 FILE_LIST.txt / SUMMARY.json / MISSING_FILES.txt
5. 默认只复制，不修改源文件

用法：
python3 tools/build_second_wave_bundle.py \
  --root "/Users/lufei/Desktop/聚核助手2.0" \
  --out  "/Users/lufei/Desktop/聚核助手2.0/第二波" \
  --force
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any


SECOND_WAVE_FILES = [
    "core/aicore/extensible_aicore.py",
    "core/aicore/config.py",
    "core/aicore/backend_manager.py",
    "core/aicore/model_backend.py",
    "core/aicore/backend_config.py",
    "core/aicore/circuit_breaker.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建三花聚顶系统第二波核心文件包")
    parser.add_argument(
        "--root",
        required=True,
        help="项目根目录，例如 /Users/lufei/Desktop/聚核助手2.0",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="输出目录，例如 /Users/lufei/Desktop/聚核助手2.0/第二波",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="如果输出目录已存在，先删除再重建",
    )
    return parser.parse_args()


def ensure_clean_output(out_dir: Path, force: bool) -> None:
    if out_dir.exists():
        if not force:
            raise FileExistsError(
                f"输出目录已存在：{out_dir}\n如确认覆盖，请加 --force"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def copy_files(root: Path, out_dir: Path) -> Dict[str, Any]:
    copied: List[str] = []
    missing: List[str] = []

    for rel in SECOND_WAVE_FILES:
        src = root / rel
        dst = out_dir / rel

        if not src.exists():
            missing.append(rel)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    return {
        "copied": copied,
        "missing": missing,
    }


def write_meta(out_dir: Path, root: Path, copied: List[str], missing: List[str]) -> None:
    file_list_path = out_dir / "FILE_LIST.txt"
    missing_path = out_dir / "MISSING_FILES.txt"
    summary_path = out_dir / "SUMMARY.json"

    file_list_path.write_text(
        "\n".join(copied) + ("\n" if copied else ""),
        encoding="utf-8",
    )

    missing_path.write_text(
        "\n".join(missing) + ("\n" if missing else ""),
        encoding="utf-8",
    )

    summary = {
        "bundle_name": "第二波",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(root),
        "output_dir": str(out_dir),
        "total_expected": len(SECOND_WAVE_FILES),
        "copied_count": len(copied),
        "missing_count": len(missing),
        "copied_files": copied,
        "missing_files": missing,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    root = Path(args.root).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    if not root.exists():
        print(f"[ERROR] 项目根目录不存在: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"[ERROR] 项目根路径不是目录: {root}", file=sys.stderr)
        return 2

    try:
        ensure_clean_output(out_dir, args.force)
        result = copy_files(root, out_dir)
        write_meta(out_dir, root, result["copied"], result["missing"])
    except Exception as e:
        print(f"[ERROR] 构建失败: {e}", file=sys.stderr)
        return 1

    print("✅ 第二波构建完成")
    print(f"项目根目录: {root}")
    print(f"输出目录:   {out_dir}")
    print(f"应复制文件: {len(SECOND_WAVE_FILES)}")
    print(f"已复制:     {len(result['copied'])}")
    print(f"缺失:       {len(result['missing'])}")
    print(f"文件清单:   {out_dir / 'FILE_LIST.txt'}")
    print(f"摘要:       {out_dir / 'SUMMARY.json'}")
    print(f"缺失清单:   {out_dir / 'MISSING_FILES.txt'}")

    if result["missing"]:
        print("\n⚠️ 缺失文件：")
        for rel in result["missing"]:
            print(f"- {rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
