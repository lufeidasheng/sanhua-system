#!/usr/bin/env python3
"""
replace_logging.py
———— 将项目里所有 `logging.xxx(` 替换为 `log.xxx(`，并插入 TraceLogger 导入语句
"""

import argparse
import os
import re
from pathlib import Path

TRACE_IMPORT = (
    "from core.core2_0.sanhuatongyu.logger import TraceLogger\n"
    "log = TraceLogger(__name__)\n"
)

# 要替换的模式
REPLACE_MAP = {
    r"\blogging\.info\(": "log.info(",
    r"\blogging\.warning\(": "log.warning(",
    r"\blogging\.error\(": "log.error(",
    r"\blogging\.debug\(": "log.debug(",
    r"\blogging\.critical\(": "log.critical(",
}

# 忽略目录
SKIP_DIRS = {"__pycache__", ".git", "venv", "env", ".mypy_cache"}

def should_skip(path: Path) -> bool:
    return any(sk in path.parts for sk in SKIP_DIRS)

def replace_in_file(p: Path) -> bool:
    text = p.read_text(encoding="utf-8")
    original = text

    # 1) 替换 logging.xxx
    for pattern, repl in REPLACE_MAP.items():
        text = re.sub(pattern, repl, text)

    # 2) 如果文件里根本没出现 “log.”，插入 TraceLogger 导入
    if "log." in text and "TraceLogger(" not in text:
        # 找到 import 块末尾行号
        lines = text.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.lstrip().startswith(("import ", "from ")):
                insert_idx = i + 1
            else:
                # 遇到非 import 行就结束
                break
        lines.insert(insert_idx, TRACE_IMPORT)
        text = "".join(lines)

    if text != original:
        p.write_text(text, encoding="utf-8")
        return True
    return False

def main(root: str):
    root_path = Path(root).resolve()
    changed = []

    for p in root_path.rglob("*.py"):
        if should_skip(p):
            continue
        try:
            if replace_in_file(p):
                changed.append(str(p.relative_to(root_path)))
        except Exception as exc:
            print(f"[!] 处理失败: {p}: {exc}")

    # 输出结果
    if changed:
        print("\n✅ 完成替换，修改文件数：", len(changed))
        for fp in changed[:20]:
            print("  -", fp)
        if len(changed) > 20:
            print(f"  ... 其余 {len(changed)-20} 个文件省略")
    else:
        print("⚠️  未找到需要替换的 logging 调用，或路径不正确。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量替换 logging 调用为 TraceLogger")
    parser.add_argument("--root", required=True, help="项目根目录绝对路径")
    args = parser.parse_args()
    main(args.root)
