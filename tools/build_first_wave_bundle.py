#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
把 _chatgpt_project_bundle_v2/FILTERED_MIRROR 中的“第一波主链文件”
复制到 _chatgpt_project_bundle_v2/第一波

特点：
- 只复制，不修改原项目源码
- 从 FILTERED_MIRROR 取文件，避免碰原始大仓库
- 保留目录结构
- 自动生成：
  - 第一波/FILE_LIST.txt
  - 第一波/MISSING_FILES.txt
  - 第一波/SUMMARY.json

推荐运行：
python3 tools/build_first_wave_bundle.py \
  --bundle "/Users/lufei/Desktop/聚核助手2.0/_chatgpt_project_bundle_v2" \
  --force
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import List, Tuple


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# 第一波：明确保留的文件 / 目录
# =========================

FIRST_WAVE_FILES = [
    # 索引与根文件
    "README.md",

    # config
    "config/aliases.yaml",
    "config/aliases.darwin.yaml",
    "config/config.py",
    "config/global_config.yaml",
    "config/global_config.json",
    "config/release_v2_whitelist.txt",

    # AICore 主链
    "core/aicore/aicore.py",
    "core/aicore/action_manager.py",
    "core/aicore/command_router.py",
    "core/aicore/backend_manager.py",
    "core/aicore/health_monitor.py",
    "core/aicore/config.py",
    "core/aicore/manifest.json",

    # Intent / Action
    "core/aicore/intent_action_generator/intent_recognizer.py",
    "core/aicore/intent_action_generator/action_synthesizer.py",
    "core/aicore/intent_action_generator/registry.py",

    # Memory / Prompt / GUI bridge
    "core/memory_engine/memory_manager.py",
    "core/prompt_engine/prompt_memory_bridge.py",
    "core/prompt_engine/prompt_manager.py",
    "core/gui_bridge/chat_orchestrator.py",
    "core/gui_bridge/gui_memory_bridge.py",
    "core/gui_bridge/alias_bootstrap.py",
    "core/gui/memory_dock.py",

    # GUI / Entry 入口
    "entry/gui_main.py",
    "entry/gui_entry/__init__.py",
    "entry/gui_entry/gui_main.py",
    "entry/gui_entry/manifest.json",
    "entry/gui_entry/module.py",

    # 审计摘要
    "audit_output/module_inventory.csv",
    "audit_output/imports_edges.csv",
    "audit_output/action_edges.csv",
    "audit_output/event_edges.csv",
    "audit_output/module_graph.dot",
    "audit_output/gui_boot_audit_report.json",
    "audit_output/system_boot_audit_report.json",

    # 最低限度测试
    "tests/test_aicore.py",
    "tests/test_entry_dispatcher.py",
    "tests/test_modules_loading.py",
]

FIRST_WAVE_DIRS = [
    # 三花统御主链
    "core/core2_0/sanhuatongyu",

    # 主战模块
    "modules/aicore_module",
    "modules/model_engine_actions",
    "modules/reply_dispatcher",
    "modules/system_monitor",
    "modules/system_control",
    "modules/code_reader",
    "modules/code_reviewer",
    "modules/code_executor",
    "modules/code_inserter",
]


def copy_file(src: Path, dst: Path) -> int:
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return src.stat().st_size


def copy_tree(src_dir: Path, dst_dir: Path) -> Tuple[int, int]:
    """
    返回: (文件数, 总字节数)
    """
    file_count = 0
    total_bytes = 0

    for path in src_dir.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src_dir)
        dst = dst_dir / rel
        ensure_dir(dst.parent)
        shutil.copy2(path, dst)
        file_count += 1
        total_bytes += path.stat().st_size

    return file_count, total_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="从 ChatGPT v2 导出包中构建 第一波 文件夹")
    parser.add_argument(
        "--bundle",
        required=True,
        help="v2 导出包根目录，例如 /Users/lufei/Desktop/聚核助手2.0/_chatgpt_project_bundle_v2"
    )
    parser.add_argument(
        "--name",
        default="第一波",
        help="输出文件夹名，默认：第一波"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="若输出目录已存在则先删除再重建"
    )
    args = parser.parse_args()

    bundle = Path(args.bundle).expanduser().resolve()
    mirror = bundle / "FILTERED_MIRROR"
    out_dir = bundle / args.name

    if not bundle.exists() or not bundle.is_dir():
        raise SystemExit(f"bundle 目录不存在：{bundle}")

    if not mirror.exists() or not mirror.is_dir():
        raise SystemExit(f"FILTERED_MIRROR 不存在：{mirror}")

    if out_dir.exists():
        if not args.force:
            raise SystemExit(f"输出目录已存在：{out_dir}\n如需覆盖请加 --force")
        shutil.rmtree(out_dir)

    ensure_dir(out_dir)

    copied_files: List[str] = []
    copied_dirs: List[str] = []
    missing_items: List[str] = []

    copied_file_count = 0
    copied_total_bytes = 0

    # 先复制显式文件
    for rel in FIRST_WAVE_FILES:
        src = mirror / rel
        dst = out_dir / rel
        if src.exists() and src.is_file():
            copied_total_bytes += copy_file(src, dst)
            copied_file_count += 1
            copied_files.append(rel)
        else:
            missing_items.append(rel)

    # 再复制目录
    for rel in FIRST_WAVE_DIRS:
        src = mirror / rel
        dst = out_dir / rel
        if src.exists() and src.is_dir():
            n, size = copy_tree(src, dst)
            copied_file_count += n
            copied_total_bytes += size
            copied_dirs.append(rel)
        else:
            missing_items.append(rel)

    # 写清单
    file_list_lines = []
    file_list_lines.append("# 第一波文件清单")
    file_list_lines.append("")
    file_list_lines.append("## 显式文件")
    for item in copied_files:
        file_list_lines.append(f"- {item}")

    file_list_lines.append("")
    file_list_lines.append("## 递归复制目录")
    for item in copied_dirs:
        file_list_lines.append(f"- {item}")

    write_text(out_dir / "FILE_LIST.txt", "\n".join(file_list_lines) + "\n")

    missing_lines = ["# 未找到的路径", ""]
    if missing_items:
        missing_lines.extend(f"- {item}" for item in missing_items)
    else:
        missing_lines.append("(无)")
    write_text(out_dir / "MISSING_FILES.txt", "\n".join(missing_lines) + "\n")

    summary = {
        "bundle_root": str(bundle),
        "mirror_root": str(mirror),
        "output_dir": str(out_dir),
        "copied_file_count": copied_file_count,
        "copied_total_bytes": copied_total_bytes,
        "explicit_files_requested": len(FIRST_WAVE_FILES),
        "explicit_dirs_requested": len(FIRST_WAVE_DIRS),
        "copied_files": copied_files,
        "copied_dirs": copied_dirs,
        "missing_items": missing_items,
    }
    write_json(out_dir / "SUMMARY.json", summary)

    print("✅ 第一波构建完成")
    print(f"输出目录: {out_dir}")
    print(f"复制文件数: {copied_file_count}")
    print(f"总字节数: {copied_total_bytes}")
    print(f"缺失项: {len(missing_items)}")
    print(f"文件清单: {out_dir / 'FILE_LIST.txt'}")
    print(f"缺失清单: {out_dir / 'MISSING_FILES.txt'}")
    print(f"摘要: {out_dir / 'SUMMARY.json'}")


if __name__ == "__main__":
    main()
