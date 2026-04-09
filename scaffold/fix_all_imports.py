#!/usr/bin/env python3
"""
fix_all_imports.py
------------------
批量替换“三花聚顶”项目在重构/迁移后产生的
Python import / from ... import ... 路径问题。

功能：
1. 按映射表批量替换导入前缀
2. 处理模块文件重命名
3. 支持多行导入语句 (import (…) 形式)
4. 自动 .bak 备份，支持恢复
5. 支持 --dry-run 仅预览 & --target 指定扫描目录

----------------------------------------------------
示例：
    # 仅预览将修改的文件
    python fix_all_imports.py --target /path/to/project --dry-run

    # 真正修改 (会备份 .bak)
    python fix_all_imports.py --target /path/to/project

    # 恢复备份
    python fix_all_imports.py --target /path/to/project --restore
"""

import argparse
import os
import pathlib
import re
import shutil

# === 1. 路径映射表：旧导入前缀 -> 新导入前缀 ===========================
PATH_MAP = {
    "core.aicore.":           "core.cognition.",
    "core.aicore.memory.":    "core.memory.",
    "core.core2_0.":          "core.execution.",
    "core.system.":           "core.system.",
    # 入口模块
    "modules.cli_entry":      "entrypoints.cli",
    "modules.gui_entry":      "entrypoints.gui",
    "modules.voice_entry":    "entrypoints.voice",
    "modules.voice_input":    "modules.voice.voice_input",
    # 其余模块保持不变但可扩展
    "core.core2_0.event_bus": "services.event_bus",
    "core.core2_0.logger":    "services.logging",
    "core.core2_0.config_manager": "services.config_manager",
}

# === 2. 模块文件重命名映射 ==========================================
MODULE_RENAMES = {
    "action_manager.py": "action_dispatcher.py",
    "model_engine.py":   "llm_integration.py",
    "jumo_core.py":      "core_engine.py",
}

# 备份文件后缀
BAK_EXT = ".bak"


# -------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------
def update_import_path(old_path: str) -> str:
    """根据映射表替换导入前缀并处理模块重命名"""
    # 路径前缀替换
    for old, new in PATH_MAP.items():
        if old_path.startswith(old):
            old_path = new + old_path[len(old):]

    # 文件名重命名
    for old_mod, new_mod in MODULE_RENAMES.items():
        if old_path.endswith(old_mod):
            old_path = old_path.replace(old_mod, new_mod)
    return old_path


def replace_multiline(match: re.Match) -> str:
    """处理多行 from ... import (a, b, ...)"""
    from_kw, old_pkg, import_kw, rest = match.groups()
    new_pkg = update_import_path(old_pkg)
    return f"{from_kw}{new_pkg}{import_kw}{rest}"


def process_file(py_path: pathlib.Path, dry: bool) -> bool:
    """替换单个 .py 文件，返回 True 表示发生修改"""
    src_text = py_path.read_text(encoding="utf-8")
    new_text = src_text

    # ---- 单行 import / from ----
    # from pkg.sub import X
    new_text = re.sub(
        r"(\bfrom\s+)([\w.]+)(\s+import\b)",
        lambda m: f"{m.group(1)}{update_import_path(m.group(2))}{m.group(3)}",
        new_text,
    )
    # import pkg.sub
    new_text = re.sub(
        r"(\bimport\s+)([\w.]+)",
        lambda m: f"{m.group(1)}{update_import_path(m.group(2))}",
        new_text,
    )

    # ---- 多行 from ... import (...) ----
    multiline_pat = re.compile(
        r"(\bfrom\s+)([\w.]+)(\s+import\s+\(?)[\s\n]*([\w\s,\\]+)\)?",
        re.MULTILINE,
    )
    new_text = multiline_pat.sub(replace_multiline, new_text)

    if new_text != src_text:
        if dry:
            print(f"PLAN  {py_path}")
        else:
            shutil.copy(py_path, f"{py_path}{BAK_EXT}")
            py_path.write_text(new_text, encoding="utf-8")
            print(f"FIX   {py_path}")
        return True
    return False


def walk_and_fix(root: pathlib.Path, dry: bool):
    """遍历项目目录批量替换导入"""
    total, modified = 0, 0
    this_script = pathlib.Path(__file__).resolve()

    for py_file in root.rglob("*.py"):
        # 跳过自身、备份、虚拟环境等
        if py_file.resolve() == this_script:
            continue
        if any(excl in py_file.parts for excl in ("dependencies", "__pycache__", "venv", ".git")):
            continue

        total += 1
        if process_file(py_file, dry):
            modified += 1

    print(f"\n扫描 {total} 个 .py 文件，{'将修改' if dry else '已修改'} {modified} 个文件")


def restore_backups(root: pathlib.Path):
    """找回所有 .bak 文件"""
    restored = 0
    for bak in root.rglob(f"*{BAK_EXT}"):
        orig = bak.with_suffix("")  # 去掉 .bak
        shutil.move(bak, orig)
        print(f"RESTORED {orig}")
        restored += 1
    print(f"\n已恢复 {restored} 个文件")


# -------------------------------------------------------------------
# 主程序
# -------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量修正导入路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入文件")
    parser.add_argument("--restore", action="store_true", help="恢复 *.bak 备份文件")
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="指定要扫描的项目根目录（默认=脚本所在目录）",
    )
    args = parser.parse_args()

    root_dir = pathlib.Path(args.target).resolve() if args.target else pathlib.Path(__file__).resolve().parent
    if not root_dir.exists():
        raise SystemExit(f"❌ 指定目录不存在: {root_dir}")

    print(f"📁 扫描目录: {root_dir}\n")

    if args.restore:
        restore_backups(root_dir)
    else:
        walk_and_fix(root_dir, args.dry_run)
        if args.dry_run:
            print("\n⚠️ Dry-run 完成：未改动任何文件。确认无误后去掉 --dry-run 重新运行。")
        else:
            print("\n✅ 导入路径修改完成！原文件备份为 .bak，可 --restore 回滚。")
            print("🔔 建议运行测试：python -m pytest tests/")
