#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶剩余语法尾巴第三轮强制修补
- speech_manager: 强制重建顶部日志初始化区
- aicore_gui: 强制清洗并重建 QtWidgets import 区，删除残留 ')'
"""

from __future__ import annotations

import argparse
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


def patch_speech_manager_strict(text: str) -> PatchOutcome:
    """
    强制把顶部日志初始化区整体替换掉。
    从以下任一行开始：
      - log_dir =
      - logging.basicConfig(
      - logging.FileHandler(
    一直到第一个 logger=/log=/class /def /if __name__ 前。
    """
    lines = text.splitlines()
    if not lines:
        return PatchOutcome(False, "空文件")

    clean_block = [
        'log_dir = os.path.abspath(',
        '    os.path.join(os.path.dirname(__file__), "..", "..", "logs")',
        ')',
        'os.makedirs(log_dir, exist_ok=True)',
        '',
        'logging.basicConfig(',
        '    level=logging.INFO,',
        "    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',",
        '    handlers=[',
        '        logging.FileHandler(',
        '            os.path.join(log_dir, "speech_manager.log"),',
        '            encoding="utf-8"',
        '        ),',
        '        logging.StreamHandler()',
        '    ]',
        ')',
        '',
    ]

    head_limit = min(len(lines), 180)

    start = None
    for i in range(head_limit):
        s = lines[i].strip()
        if (
            s.startswith("log_dir =")
            or s.startswith("logging.basicConfig(")
            or "logging.FileHandler(" in s
        ):
            start = i
            break

    if start is None:
        return PatchOutcome(False, "未找到 speech_manager 顶部日志区起点")

    end = None
    for j in range(start + 1, head_limit):
        s = lines[j].strip()
        if (
            s.startswith("logger =")
            or s.startswith("log =")
            or s.startswith("class ")
            or s.startswith("def ")
            or s.startswith("if __name__")
        ):
            end = j
            break

    if end is None:
        end = head_limit

    new_lines = lines[:start] + clean_block + lines[end:]
    new_text = "\n".join(new_lines).rstrip() + "\n"

    if new_text == text:
        return PatchOutcome(False, "speech_manager 顶部日志区已是目标状态")

    return PatchOutcome(True, "强制重建 speech_manager 顶部日志初始化区", new_text)


def patch_aicore_gui_strict(text: str) -> PatchOutcome:
    """
    强制清洗 aicore_gui 顶部 import 区：
    - 删除所有 QtWidgets 相关污染行
    - 删除顶部残留的独立 ')'
    - 在 get_global_dispatcher 下插入干净 QtWidgets import
    """
    lines = text.splitlines()
    if not lines:
        return PatchOutcome(False, "空文件")

    clean_block = [
        "from PyQt5.QtWidgets import (",
        "    QApplication,",
        "    QWidget,",
        "    QVBoxLayout,",
        "    QTextEdit,",
        "    QLineEdit,",
        "    QPushButton,",
        "    QLabel,",
        "    QHBoxLayout,",
        "    QCheckBox,",
        "    QFileDialog,",
        "    QMessageBox,",
        ")",
    ]

    head_limit = min(len(lines), 120)
    head = lines[:head_limit]
    tail = lines[head_limit:]

    widget_tokens = {
        "QApplication", "QWidget", "QVBoxLayout", "QTextEdit", "QLineEdit",
        "QPushButton", "QLabel", "QHBoxLayout", "QCheckBox",
        "QFileDialog", "QMessageBox"
    }

    cleaned = []
    removed_any = False

    for idx, line in enumerate(head):
        s = line.strip()

        # 清掉所有 QtWidgets 相关坏行
        if "PyQt5.QtWidgets" in s:
            removed_any = True
            continue

        if s.startswith("import ") and any(tok in s for tok in widget_tokens):
            removed_any = True
            continue

        # continuation / 残留 widget 行
        if any(tok in s for tok in widget_tokens) and ("," in s or s.endswith("\\") or s.startswith("Q")):
            removed_any = True
            continue

        # 顶部导入区残留的独立右括号直接删
        if idx < 80 and s == ")":
            removed_any = True
            continue

        cleaned.append(line)

    # 找插入位置：get_global_dispatcher 后
    insert_idx = None
    for i, line in enumerate(cleaned):
        if "get_global_dispatcher" in line:
            insert_idx = i + 1
            break

    if insert_idx is None:
        last_import = -1
        for i, line in enumerate(cleaned):
            if line.startswith("import ") or line.startswith("from "):
                last_import = i
        insert_idx = last_import + 1 if last_import >= 0 else 0

    rebuilt_head = cleaned[:insert_idx] + [""] + clean_block + [""] + cleaned[insert_idx:]
    new_text = "\n".join(rebuilt_head + tail).rstrip() + "\n"

    if new_text == text:
        return PatchOutcome(False, "aicore_gui 顶部 import 区已是目标状态")

    reason = "强制重建 aicore_gui 顶部 QtWidgets import 区"
    if removed_any:
        reason += " 并清理残留垃圾"
    return PatchOutcome(True, reason, new_text)


PATCH_TARGETS = {
    "模块/speech_manager/speech_manager.py": patch_speech_manager_strict,
    "gui/aicore_gui.py": patch_aicore_gui_strict,
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
    parser = argparse.ArgumentParser(description="三花聚顶剩余语法尾巴第三轮强制修补")
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
    print("三花聚顶剩余语法尾巴第三轮强制修补")
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
        print(f'  python3 tools/fix_sanhua_tail_3.py --root "{root}"')
    else:
        print("")
        print("建议立刻复检：")
        print(f'  python3 tools/sanhua_system_audit.py --root "{root}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
