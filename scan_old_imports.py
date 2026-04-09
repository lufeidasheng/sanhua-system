#!/usr/bin/env python3
"""
scan_old_imports.py

递归扫描指定目录下的所有 Python 文件，
检测是否包含指定的旧导入路径字符串。

用法:
    python scan_old_imports.py --root /path/to/project

支持排除目录，默认排除常见虚拟环境和缓存目录。

"""

import argparse
import pathlib

# 默认排除的目录名称
DEFAULT_EXCLUDES = {
    "dependencies", "__pycache__", "rollback_snapshots",
    ".git", "runtime", "recordings", "venv", "env", ".env"
}

def scan_files(root: pathlib.Path, keywords, exclude_dirs):
    for path in root.rglob("*.py"):
        if any(excl in path.parts for excl in exclude_dirs):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] 读取文件失败 {path}: {e}")
            continue
        for kw in keywords:
            if kw in text:
                # 找出具体行号和内容
                lines = text.splitlines()
                for i, line in enumerate(lines, 1):
                    if kw in line:
                        print(f"{path}:{i}: {line.strip()}")

def main():
    parser = argparse.ArgumentParser(description="扫描项目中的旧导入路径")
    parser.add_argument("--root", type=str, default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--exclude", type=str, nargs="*", default=list(DEFAULT_EXCLUDES),
                        help="排除的目录名称列表")
    parser.add_argument("--keywords", type=str, nargs="+", required=True,
                        help="要检测的旧导入路径关键词列表")
    args = parser.parse_args()

    root_path = pathlib.Path(args.root).resolve()
    exclude_dirs = set(args.exclude)

    print(f"扫描目录: {root_path}")
    print(f"排除目录: {exclude_dirs}")
    print(f"检测关键词: {args.keywords}")
    print()

    scan_files(root_path, args.keywords, exclude_dirs)

if __name__ == "__main__":
    main()
