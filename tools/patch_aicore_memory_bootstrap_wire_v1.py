#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


def backup_file(src: Path, root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / stamp
    dst = backup_root / src.relative_to(root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def patch_aicore_text(text: str) -> tuple[str, str]:
    if "step\": \"memory_actions\"" in text or "step': 'memory_actions'" in text:
        return text, "SKIP: 已存在 memory_actions 注入逻辑"

    # ------------------------------------------------------------
    # 1) 修正 core_bootstrap_ready 逻辑
    #    让 memory 缺失时不会提前 early-return
    # ------------------------------------------------------------
    old_ready_exact = """        core_bootstrap_ready = (
            has_ai
            and (has_sysmon or has_system or has_memory)
            and (has_code_reader or has_code_reviewer or has_code_executor)
        )
"""
    new_ready_exact = """        core_bootstrap_ready = (
            has_ai
            and (has_sysmon or has_system)
            and has_memory
            and (has_code_reader or has_code_reviewer or has_code_executor)
        )
"""
    if old_ready_exact in text:
        text = text.replace(old_ready_exact, new_ready_exact, 1)
    else:
        # 尝试正则替换
        pattern = re.compile(
            r"""
(?P<indent>[ \t]*)
core_bootstrap_ready\s*=\s*\(
.*?
\)
(?=\n[ \t]*if\s+count_before\s*>\s*0\s+and\s+core_bootstrap_ready\s+and\s+not\s+force:)
""",
            re.S | re.X,
        )
        repl = (
            "        core_bootstrap_ready = (\n"
            "            has_ai\n"
            "            and (has_sysmon or has_system)\n"
            "            and has_memory\n"
            "            and (has_code_reader or has_code_reviewer or has_code_executor)\n"
            "        )"
        )
        new_text, n = pattern.subn(repl, text, count=1)
        if n > 0:
            text = new_text

    # ------------------------------------------------------------
    # 2) 注入 memory actions bootstrap
    # ------------------------------------------------------------
    injection_block = """
        # 4.5) memory actions
        try:
            from tools.memory_actions_official import register_actions as register_memory_actions
            mem_res = register_memory_actions(dispatcher=dispatcher, aicore=self)
            details.append({
                "step": "memory_actions",
                "ok": bool(mem_res.get("ok")),
                "count_registered": int(mem_res.get("count_registered", 0)),
                "count_failed": int(mem_res.get("count_failed", 0)),
                "registered": list(mem_res.get("registered", [])),
                "failed": list(mem_res.get("failed", [])),
            })
        except Exception as e:
            details.append({
                "step": "memory_actions",
                "ok": False,
                "error": str(e),
            })

"""

    anchor_candidates = [
        "        # 5) fallback safe action: sysmon.status\n",
        "        # 5) fallback safe actions\n",
        "        count_after = _list_count()\n",
    ]

    injected = False
    for anchor in anchor_candidates:
        if anchor in text:
            text = text.replace(anchor, injection_block + anchor, 1)
            injected = True
            break

    if not injected:
        return text, "ERROR: 未找到 memory_actions 注入锚点"

    return text, "PATCHED"


def main() -> int:
    parser = argparse.ArgumentParser(description="给 AICore 的 bootstrap 注入 memory actions 自动注册")
    parser.add_argument("--root", required=True, help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"

    print("=" * 72)
    print("aicore memory bootstrap wire v1 补丁开始")
    print("=" * 72)

    if not target.exists():
        print(f"[ERROR  ] {target}")
        print("原因: aicore.py 不存在")
        print("=" * 72)
        return 2

    old_text = target.read_text(encoding="utf-8")
    new_text, status = patch_aicore_text(old_text)

    if status.startswith("SKIP"):
        print(f"[SKIP   ] {target}")
        print(f"原因: {status}")
        print("=" * 72)
        return 0

    if status.startswith("ERROR"):
        print(f"[ERROR  ] {target}")
        print(f"原因: {status}")
        print("=" * 72)
        print("下一步建议：")
        print(f'  python3 -m py_compile "{target}"')
        print(f'  python3 "{root / "tools" / "test_memory_bootstrap_persistence.py"}"')
        print("=" * 72)
        return 1

    backup = backup_file(target, root)
    target.write_text(new_text, encoding="utf-8")

    print(f"[BACKUP ] {backup}")
    print(f"[PATCHED] {target}")
    print("=" * 72)
    print("修复点：")
    print(" - bootstrap 自动注册 memory.* 动作")
    print(" - 修复 core_bootstrap_ready 过早 short-circuit")
    print(" - 让 get_aicore_instance() 启动后即可拥有 memory dispatcher actions")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 -m py_compile "{target}"')
    print(f'  python3 "{root / "tools" / "test_memory_bootstrap_persistence.py"}"')
    print(f'  python3 "{root / "tools" / "boot_readiness_check.py"}"')
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
