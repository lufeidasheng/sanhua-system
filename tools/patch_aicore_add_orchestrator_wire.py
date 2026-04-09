#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


TARGET_REL = Path("core/aicore/aicore.py")
INSERT_AFTER = "_AICORE_SINGLETON = _wire_self_evolution_support(_AICORE_SINGLETON)"
INSERT_LINE = "_AICORE_SINGLETON = _wire_self_evolution_orchestrator_support(_AICORE_SINGLETON)"
REQUIRED_FUNC = "def _wire_self_evolution_orchestrator_support(aicore: Any) -> Any:"


def make_backup(root: Path, target_file: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / TARGET_REL
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_file, backup_path)
    return backup_path


def patch_file(target_file: Path) -> str:
    text = target_file.read_text(encoding="utf-8")

    if REQUIRED_FUNC not in text:
        raise RuntimeError(
            "未找到 _wire_self_evolution_orchestrator_support(...) 函数定义，"
            "请先把 orchestrator 挂载函数写进 aicore.py 再执行本补丁。"
        )

    if INSERT_LINE in text:
        return "already_patched"

    marker = INSERT_AFTER
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(
            "未找到预期锚点：\n"
            f"  {INSERT_AFTER}\n"
            "说明 aicore.py 当前结构和预期不一致，需要手动检查。"
        )

    line_end = text.find("\n", idx)
    if line_end < 0:
        line_end = len(text)

    insert_block = "\n\n            # 5) 自演化编排器\n            " + INSERT_LINE
    new_text = text[:line_end] + insert_block + text[line_end:]

    target_file.write_text(new_text, encoding="utf-8")
    return "patched"


def main() -> int:
    parser = argparse.ArgumentParser(description="给 aicore.py 注入 orchestrator 挂载调用")
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target_file = root / TARGET_REL

    if not target_file.exists():
        print(f"[ERROR] 文件不存在: {target_file}")
        return 1

    try:
        backup_path = make_backup(root, target_file)
        result = patch_file(target_file)

        print("=" * 72)
        print("aicore orchestrator 挂载补丁完成")
        print("=" * 72)

        if result == "already_patched":
            print(f"[SKIP   ] {target_file}")
            print("原因: 已存在 orchestrator 挂载调用，未重复注入")
        else:
            print(f"[PATCHED] {target_file}")

        print(f"[BACKUP ] {backup_path}")
        print()
        print("下一步建议：")
        print(f'  python3 -m py_compile "{target_file}"')
        print(f'  python3 - <<\'PY\'')
        print("from core.aicore.aicore import get_aicore_instance")
        print("a = get_aicore_instance()")
        print('print("orchestrator:", hasattr(a, "evolve_file_replace"))')
        print("PY")
        print("=" * 72)
        return 0

    except Exception as e:
        print("=" * 72)
        print("aicore orchestrator 挂载补丁失败")
        print("=" * 72)
        print(f"[ERROR] {e}")
        print("=" * 72)
        return 1


if __name__ == "__main__":
    sys.exit(main())
