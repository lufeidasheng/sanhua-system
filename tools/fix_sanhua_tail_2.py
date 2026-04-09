#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶剩余语法尾巴定向修补脚本
==================================================
目标：
1. 修复 模块/speech_manager/speech_manager.py 的 unexpected indent
2. 修复 gui/aicore_gui.py 的残留 PyQt5 import 语法错误
3. 自动备份被修改文件

使用：
  python3 tools/fix_sanhua_tail_2.py --root "/Users/lufei/Desktop/聚核助手2.0" --dry-run
  python3 tools/fix_sanhua_tail_2.py --root "/Users/lufei/Desktop/聚核助手2.0"
"""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


ENCODINGS = ("utf-8", "utf-8-sig", "gbk", "latin-1")


def safe_read_text(path: Path) -> str:
    for enc in ENCODINGS:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def backup_file(src: Path, root: Path, backup_root: Path) -> Path:
    dst = backup_root / relpath(src, root)
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return dst


@dataclass
class PatchOutcome:
    changed: bool
    reason: str
    new_text: Optional[str] = None


# ============================================================
# Patch 1: speech_manager 残留缩进垃圾清理
# ============================================================

def patch_speech_manager_tail(text: str) -> PatchOutcome:
    """
    目标：
    - 统一重建顶部 log_dir + logging.basicConfig 块
    - 清除第一轮补丁后可能残留的缩进垃圾
    - 尽量不碰业务逻辑

    处理策略：
    1. 锁定从 log_dir/logging.basicConfig 开始，到 logger/log/class/def 前的日志初始化区
    2. 整段替换成干净版本
    """

    clean_block = """log_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs")
)
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, "speech_manager.log"),
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)
"""

    # 方案 A：优先从 log_dir / logging.basicConfig 到 logger/log/class/def 前整体替换
    pattern_a = re.compile(
        r"""
        (?P<prefix>
            (?:
                ^.*?$
                \n
            )*?
        )
        (?P<block>
            (?:
                log_dir\s*=.*?
                |
                logging\.basicConfig\(
            )
            .*?
        )
        (?=
            ^
            (?:logger|log)\s*=
            |
            ^
            class\s+
            |
            ^
            def\s+
            |
            ^
            if\s+__name__
        )
        """,
        re.S | re.M | re.X,
    )

    # 只在前 180 行内动手，避免误伤后面的业务代码
    lines = text.splitlines()
    head = "\n".join(lines[:180])
    tail = "\n".join(lines[180:])

    # 如果已经是干净块，并且 head 里不再有异常残留，直接跳过
    if clean_block.strip() in head and "log_dir = os.path.abspath(log_dir)" not in head:
        return PatchOutcome(False, "speech_manager 顶部日志块已基本正常")

    m = pattern_a.search(head)
    if m:
        start, end = m.span("block")
        new_head = head[:start] + clean_block + "\n" + head[end:]
        new_text = new_head + ("\n" + tail if tail else "")
        return PatchOutcome(True, "重建 speech_manager 顶部日志初始化区", new_text)

    # 方案 B：兜底，从 logging.basicConfig 到 logger/log/class/def 前替换
    pattern_b = re.compile(
        r"""
        logging\.basicConfig\(
        .*?
        \)
        \s*
        (?=
            ^
            (?:logger|log)\s*=
            |
            ^
            class\s+
            |
            ^
            def\s+
            |
            ^
            if\s+__name__
        )
        """,
        re.S | re.M | re.X,
    )

    new_head, count = pattern_b.subn(clean_block + "\n", head, count=1)
    if count > 0:
        return PatchOutcome(True, "兜底重建 speech_manager 的 basicConfig 块", new_head + ("\n" + tail if tail else ""))

    return PatchOutcome(False, "未命中 speech_manager 顶部日志区，请人工核对")


# ============================================================
# Patch 2: aicore_gui 残留 PyQt5 import 垃圾清理
# ============================================================

def patch_aicore_gui_tail(text: str) -> PatchOutcome:
    """
    目标：
    - 清除残留的 broken PyQt5.QtWidgets import 垃圾
    - 重建唯一的干净 QtWidgets 导入块
    """

    clean_block = """from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QCheckBox,
    QFileDialog,
    QMessageBox,
)
"""

    lines = text.splitlines()
    changed = False

    # 只清理前 120 行的 import 区
    head_lines = lines[:120]
    tail_lines = lines[120:]

    new_head = []
    skip_mode = False
    removed_any = False

    def is_broken_qtwidgets_line(s: str) -> bool:
        t = s.strip()
        if "PyQt5.QtWidgets" in t:
            return True
        if t.startswith("import QApplication"):
            return True
        if ("QPushButton" in t and "QMessageBox" in t):
            return True
        return False

    for line in head_lines:
        if is_broken_qtwidgets_line(line):
            removed_any = True
            skip_mode = True
            continue

        if skip_mode:
            t = line.strip()
            # continuation lines / stray remnants
            if (
                not t
                or t == ")"
                or t.endswith("\\")
                or any(x in t for x in [
                    "QApplication", "QWidget", "QVBoxLayout", "QTextEdit",
                    "QLineEdit", "QPushButton", "QLabel", "QHBoxLayout",
                    "QCheckBox", "QFileDialog", "QMessageBox"
                ])
            ):
                removed_any = True
                continue
            else:
                skip_mode = False

        new_head.append(line)

    # 如果没找到垃圾，但已经有干净块，就跳过
    head_joined = "\n".join(new_head)
    if clean_block.strip() in head_joined and not removed_any:
        return PatchOutcome(False, "aicore_gui 的 QtWidgets import 已正常")

    # 插入到 get_global_dispatcher 下面；找不到就插到 import 区尾部
    insert_idx = None
    for i, line in enumerate(new_head):
        if "get_global_dispatcher" in line:
            insert_idx = i + 1
            break

    if insert_idx is None:
        # 插入到顶部 import 区最后一个 import 之后
        last_import = -1
        for i, line in enumerate(new_head):
            if line.startswith("import ") or line.startswith("from "):
                last_import = i
        insert_idx = last_import + 1 if last_import >= 0 else 0

    block_lines = clean_block.rstrip("\n").splitlines()
    rebuilt_head = new_head[:insert_idx] + [""] + block_lines + [""] + new_head[insert_idx:]

    new_text = "\n".join(rebuilt_head + tail_lines)
    if new_text != text:
        changed = True

    if changed:
        return PatchOutcome(True, "重建 aicore_gui 的 QtWidgets import 块", new_text)

    return PatchOutcome(False, "未发生变化")


# ============================================================
# 执行框架
# ============================================================

PATCH_TARGETS = {
    "模块/speech_manager/speech_manager.py": patch_speech_manager_tail,
    "gui/aicore_gui.py": patch_aicore_gui_tail,
}


def apply_patch_file(
    file_path: Path,
    root: Path,
    backup_root: Path,
    patch_func,
    dry_run: bool,
) -> Tuple[bool, str]:
    if not file_path.exists():
        return False, "文件不存在"

    text = safe_read_text(file_path)
    outcome = patch_func(text)

    if not outcome.changed:
        return False, outcome.reason

    if outcome.new_text is None or outcome.new_text == text:
        return False, "补丁未产生实际变更"

    if not dry_run:
        backup_file(file_path, root, backup_root)
        safe_write_text(file_path, outcome.new_text)

    return True, outcome.reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三花聚顶剩余语法尾巴定向修补脚本")
    parser.add_argument("--root", type=str, default=".", help="项目根目录")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不写入")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    if not root.exists() or not root.is_dir():
        print(f"[ERROR] 根目录不存在或不是目录：{root}")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    ensure_dir(backup_root)

    print("=" * 72)
    print("三花聚顶剩余语法尾巴修补")
    print("=" * 72)
    print(f"根目录        : {root}")
    print(f"模式          : {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"备份目录      : {backup_root}")
    print("")

    changed_count = 0
    checked_count = 0

    for rel, patch_func in PATCH_TARGETS.items():
        checked_count += 1
        path = root / rel
        changed, reason = apply_patch_file(
            file_path=path,
            root=root,
            backup_root=backup_root,
            patch_func=patch_func,
            dry_run=args.dry_run,
        )
        flag = "PATCHED" if changed else "SKIP"
        print(f"[{flag}] {rel} -> {reason}")
        if changed:
            changed_count += 1

    print("")
    print("=" * 72)
    print("处理完成")
    print("=" * 72)
    print(f"目标数        : {checked_count}")
    print(f"变更数        : {changed_count}")
    print(f"写入模式      : {'否（dry-run）' if args.dry_run else '是'}")
    print("=" * 72)

    if args.dry_run:
        print("")
        print("下一步：")
        print(f"  python3 tools/fix_sanhua_tail_2.py --root \"{root}\"")
    else:
        print("")
        print("建议立刻复检：")
        print(f"  python3 tools/sanhua_system_audit.py --root \"{root}\"")
        print("再单独检查语法错误是否归零。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
