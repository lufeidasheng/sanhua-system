#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


def backup_file(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / target.parent.relative_to(root)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / target.name
    shutil.copy2(target, backup_path)
    return backup_path


def normalize_raw_regex_strings(text: str) -> tuple[str, int]:
    """
    修复 code_reviewer 里类似这种错误写法：
        re.search(r"\\bexec\\s*\\(", line)

    自动改成：
        re.search(r"\bexec\s*\(", line)

    只处理 re.<method>(r"...", ...) / re.<method>(r'...', ...) 这种原始正则字面量。
    """

    changed = 0

    # 匹配 re.search / re.match / re.findall / re.finditer / re.sub / re.fullmatch
    # 对其中的 raw string 内容做“\\ -> \”的一次降级
    pattern = re.compile(
        r"""re\.(search|match|findall|finditer|fullmatch|sub)\(\s*r(?P<quote>["'])(?P<body>(?:\\.|(?! (?P=quote) ).)*) (?P=quote)""",
        re.VERBOSE | re.DOTALL,
    )

    def repl(m: re.Match) -> str:
        nonlocal changed
        method = m.group(1)
        quote = m.group("quote")
        body = m.group("body")

        # 只在存在双反斜杠时处理，避免误改正常模式
        if "\\\\" not in body:
            return m.group(0)

        new_body = body.replace("\\\\", "\\")
        if new_body != body:
            changed += 1

        return f're.{method}(r{quote}{new_body}{quote}'

    new_text = pattern.sub(repl, text)
    return new_text, changed


def main():
    ap = argparse.ArgumentParser(description="修复 code_reviewer 模块中的双重转义正则")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "code_reviewer" / "module.py"

    if not target.exists():
        print(f"[ERROR] 未找到文件: {target}")
        raise SystemExit(1)

    old_text = target.read_text(encoding="utf-8", errors="ignore")
    new_text, changed = normalize_raw_regex_strings(old_text)

    if changed == 0:
        print("[SKIP] 未发现需要修复的双重转义 regex")
        return

    backup_path = backup_file(root, target)
    target.write_text(new_text, encoding="utf-8")

    print("=" * 72)
    print("code_reviewer regex 修复完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_path}")
    print(f"修复条数: {changed}")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root / "tools" / "test_code_reviewer_official.py"}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
