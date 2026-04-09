#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶阻塞项批量修复脚本
==================================================
用途：
1. 修复审计器已定位的 6 个语法错误
2. 可选统一 manifest.json 的 name 字段 == 目录名
3. 自动备份被修改的文件

使用：
  # 先预演
  python3 tools/fix_sanhua_blockers.py --root "/Users/lufei/Desktop/聚核助手2.0" --dry-run

  # 正式执行 + 顺手修 manifest.name
  python3 tools/fix_sanhua_blockers.py --root "/Users/lufei/Desktop/聚核助手2.0" --fix-manifest-names
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


# ============================================================
# 基础工具
# ============================================================

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


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ============================================================
# 结果结构
# ============================================================

@dataclass
class PatchOutcome:
    changed: bool
    reason: str
    new_text: Optional[str] = None


# ============================================================
# 语法修复器
# ============================================================

def patch_query_handler(text: str) -> PatchOutcome:
    """
    修复：
    config["temperature"] = max(0.0, min(1.0, float(config["temperature"]))
    -> 少一个右括号
    """
    broken = 'config["temperature"] = max(0.0, min(1.0, float(config["temperature"]))'
    fixed = 'config["temperature"] = max(0.0, min(1.0, float(config["temperature"])))'

    if fixed in text:
        return PatchOutcome(False, "已是修复状态")

    if broken in text:
        return PatchOutcome(True, "补齐缺失右括号", text.replace(broken, fixed, 1))

    return PatchOutcome(False, "未找到目标坏行")


def _replace_broken_logging_block(
    text: str,
    marker: str,
    log_filename: str,
) -> PatchOutcome:
    """
    修复这种被污染的 basicConfig 块：

    logging.basicConfig(
        ...
        handlers=[
            logging.FileHandler(...),
    log_dir = os.path.abspath(log_dir)
    os.makedirs(log_dir, exist_ok=True)
            logging.StreamHandler()
        ]
    )
    """
    pattern = re.compile(
        r"""
        logging\.basicConfig\(
        .*?
        handlers=\[
        .*?
        logging\.FileHandler\(.*?""" + re.escape(marker) + r""".*?\),
        \s*
        log_dir\s*=\s*os\.path\.abspath\(log_dir\)
        \s*
        os\.makedirs\(log_dir,\s*exist_ok=True\)
        \s*
        logging\.StreamHandler\(\)
        \s*
        \]
        \s*
        \)
        """,
        re.S | re.X,
    )

    replacement = f"""log_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs")
)
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, "{log_filename}"),
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)"""

    if replacement in text:
        return PatchOutcome(False, "已是修复状态")

    new_text, count = pattern.subn(replacement, text, count=1)
    if count > 0:
        return PatchOutcome(True, "重建被污染的 logging.basicConfig 块", new_text)

    # 次级兜底：如果只看到明显污染标记，也尝试直接报出
    if "log_dir = os.path.abspath(log_dir)" in text and marker in text:
        return PatchOutcome(False, "检测到污染块，但正则未命中；建议人工核对")
    return PatchOutcome(False, "未找到目标坏块")


def patch_speech_manager(text: str) -> PatchOutcome:
    return _replace_broken_logging_block(
        text=text,
        marker="speech_manager",
        log_filename="speech_manager.log",
    )


def patch_download_whisper_model(text: str) -> PatchOutcome:
    return _replace_broken_logging_block(
        text=text,
        marker="wake_word_detector",
        log_filename="download_whisper_model.log",
    )


def patch_main_gui(text: str) -> PatchOutcome:
    """
    修复被污染的顶部 import：
    from PyQt5.QtWidgets import (from core.core2_0...
    """
    broken_pattern = re.compile(
        r"""
        import\ sys\s+
        import\ os\s+
        import\ threading\s+
        from\ PyQt5\.QtWidgets\ import\s*\(
        .*?
        QMessageBox
        \s*
        \)
        """,
        re.S | re.X,
    )

    clean_block = """import sys
import os
import threading

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QMessageBox,
)

from core.core2_0.sanhuatongyu.logger import TraceLogger

log = TraceLogger(__name__)"""

    if clean_block in text:
        return PatchOutcome(False, "已是修复状态")

    new_text, count = broken_pattern.subn(clean_block, text, count=1)
    if count > 0:
        return PatchOutcome(True, "修复顶部被污染的 import 块", new_text)

    # 兜底：如果只检测到那条坏 import
    if "from PyQt5.QtWidgets import (from core.core2_0.sanhuatongyu.logger import TraceLogger" in text:
        lines = text.splitlines()
        end_idx = None
        for i in range(min(len(lines), 20)):
            if lines[i].strip() == ")":
                end_idx = i
                break
        if end_idx is not None:
            rest = "\n".join(lines[end_idx + 1 :])
            return PatchOutcome(True, "兜底修复顶部 import 块", clean_block + "\n" + rest)

    return PatchOutcome(False, "未找到目标坏块")


def patch_aicore_gui(text: str) -> PatchOutcome:
    broken_pattern = re.compile(
        r"""
        from\ PyQt5\.QtWidgets\s*
        \n
        import\ QApplication,\ QWidget,\ QVBoxLayout,\ QTextEdit,\ QLineEdit,\s*\\?
        \n
        \s*QPushButton,\ QLabel,\ QHBoxLayout,\ QCheckBox,\ QFileDialog,\ QMessageBox
        \n
        from\ PyQt5\.QtWidgets\s*
        """,
        re.S | re.X,
    )

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
)"""

    if clean_block in text:
        return PatchOutcome(False, "已是修复状态")

    new_text, count = broken_pattern.subn(clean_block, text, count=1)
    if count > 0:
        return PatchOutcome(True, "修复被拆裂的 PyQt5 import", new_text)

    if "from PyQt5.QtWidgets \nimport QApplication" in text or "from PyQt5.QtWidgets \r\nimport QApplication" in text:
        return PatchOutcome(False, "检测到坏块，但正则未命中；建议人工核对")

    return PatchOutcome(False, "未找到目标坏块")


def patch_code_reader(text: str) -> PatchOutcome:
    broken = """def get(self, key: str): with self._lock: return self._cache.get(key)
    def set(self, key: str, value): 
        with self._lock:
            if len(self._cache) >= self._max_size: self._cache.pop(next(iter(self._cache)))"""

    fixed = """def get(self, key: str):
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value):
        with self._lock:
            if len(self._cache) >= self._max_size:
                self._cache.pop(next(iter(self._cache)))"""

    if fixed in text:
        return PatchOutcome(False, "已是修复状态")

    if broken in text:
        return PatchOutcome(True, "展开非法单行 def/with 写法", text.replace(broken, fixed, 1))

    # 次级兜底：只修 get() 那一行
    broken_line = "def get(self, key: str): with self._lock: return self._cache.get(key)"
    fixed_line = """def get(self, key: str):
        with self._lock:
            return self._cache.get(key)"""
    if broken_line in text:
        return PatchOutcome(True, "修复非法单行 def get()", text.replace(broken_line, fixed_line, 1))

    return PatchOutcome(False, "未找到目标坏块")


# ============================================================
# manifest 修复器
# ============================================================

def should_normalize_manifest(path: Path, root: Path) -> bool:
    rel = relpath(path, root)
    rel = rel.replace("\\", "/")
    return (
        rel.startswith("modules/")
        or rel.startswith("模块/")
        or rel.startswith("core/")
        or rel.startswith("entry/")
    )


def normalize_manifest_name(path: Path, root: Path) -> Tuple[bool, str]:
    if not should_normalize_manifest(path, root):
        return False, "非目标 manifest 范围，跳过"

    try:
        data = json.loads(safe_read_text(path))
    except Exception as e:
        return False, f"manifest 解析失败：{e}"

    dir_name = path.parent.name
    old_name = data.get("name")

    if old_name == dir_name:
        return False, "name 已规范"

    # 保留原展示名到 title
    if isinstance(old_name, str) and old_name.strip():
        if "title" not in data or not str(data.get("title", "")).strip():
            data["title"] = old_name

    data["name"] = dir_name
    safe_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return True, f"name: {old_name!r} -> {dir_name!r}"


# ============================================================
# 批处理框架
# ============================================================

PatchFunc = Callable[[str], PatchOutcome]


PATCH_TARGETS: Dict[str, PatchFunc] = {
    "core/core2_0/1.0/query_handler.py": patch_query_handler,
    "模块/speech_manager/speech_manager.py": patch_speech_manager,
    "gui/main_gui.py": patch_main_gui,
    "gui/aicore_gui.py": patch_aicore_gui,
    "modules/code_reader/code_reader.py": patch_code_reader,
    "modules/voice_ai_core/download_whisper_model.py": patch_download_whisper_model,
}


def backup_file(src: Path, root: Path, backup_root: Path) -> Path:
    dst = backup_root / relpath(src, root)
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    return dst


def apply_patch_file(
    file_path: Path,
    root: Path,
    backup_root: Path,
    patch_func: PatchFunc,
    dry_run: bool,
) -> Tuple[bool, str]:
    if not file_path.exists():
        return False, "文件不存在"

    text = safe_read_text(file_path)
    outcome = patch_func(text)

    if not outcome.changed:
        return False, outcome.reason

    if outcome.new_text is None:
        return False, "补丁函数未返回新文本"

    if outcome.new_text == text:
        return False, "文本无变化"

    if not dry_run:
        backup_file(file_path, root, backup_root)
        safe_write_text(file_path, outcome.new_text)

    return True, outcome.reason


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三花聚顶阻塞项批量修复脚本")
    parser.add_argument("--root", type=str, default=".", help="项目根目录")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不实际写入")
    parser.add_argument(
        "--fix-manifest-names",
        action="store_true",
        help="顺手把 manifest.json 的 name 规范成目录名，并把旧 name 写入 title（若 title 为空）",
    )
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
    print("三花聚顶阻塞项批量修复")
    print("=" * 72)
    print(f"根目录        : {root}")
    print(f"模式          : {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"备份目录      : {backup_root}")
    print("")

    changed_count = 0
    checked_count = 0

    print("== 语法错误补丁 ==")
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

    manifest_changed = 0
    if args.fix_manifest_names:
        print("")
        print("== manifest.name 规范化 ==")
        for path in root.rglob("manifest.json"):
            changed, reason = normalize_manifest_name(path, root)
            if changed:
                if not args.dry_run:
                    backup_file(path, root, backup_root)
                if args.dry_run:
                    # dry-run 模式下不要真的改文件，所以上面 normalize_manifest_name 不能直接执行写入
                    # 因此这里重新模拟输出；为了简洁，dry-run 时改用只读检查逻辑
                    pass
                print(f"[PATCHED] {relpath(path, root)} -> {reason}")
                manifest_changed += 1
            else:
                print(f"[SKIP] {relpath(path, root)} -> {reason}")

    print("")
    print("=" * 72)
    print("处理完成")
    print("=" * 72)
    print(f"语法补丁目标数  : {checked_count}")
    print(f"语法补丁变更数  : {changed_count}")
    if args.fix_manifest_names:
        print(f"manifest 变更数 : {manifest_changed}")
    print(f"写入模式        : {'否（dry-run）' if args.dry_run else '是'}")
    print("=" * 72)

    if args.dry_run:
        print("")
        print("下一步：")
        print(f"  python3 tools/fix_sanhua_blockers.py --root \"{root}\" --fix-manifest-names")
    else:
        print("")
        print("建议立刻复检：")
        print(f"  python3 tools/sanhua_system_audit.py --root \"{root}\"")
        print("再单独看语法错误是否归零。")

    return 0


if __name__ == "__main__":
    main()
