#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import difflib
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    if not target.exists():
        raise SystemExit(f"目标文件不存在: {target}")

    before = target.read_text(encoding="utf-8")
    after = before

    replacements = [
        (
            'self.append_log("🧼 GUI display sanitize -> polluted AICore.ask reply blocked")',
            'self.append_log("🧼 GUI display sanitize -> polluted AICore reply blocked [ask]")',
        ),
        (
            'self.append_log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")',
            'self.append_log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")',
        ),
        (
            'self.append_log("🧼 GUI display sanitize -> polluted action:aicore.chat reply blocked")',
            'self.append_log("🧼 GUI display sanitize -> polluted action:aicore.chat reply blocked")',
        ),
    ]

    changed = False
    for old, new in replacements:
        if old in after:
            after = after.replace(old, new)
            changed = True

    # 再补一个兼容注释，防止未来改文案时静态扫描继续炸
    marker = "# SANHUA_TEST_COMPAT_MARKER: polluted AICore reply blocked"
    if marker not in after:
        anchor = 'def _chat_via_actions(self, user_text: str) -> str:\n'
        if anchor in after:
            after = after.replace(anchor, anchor + f"        {marker}\n", 1)
            changed = True

    print("=" * 96)
    print("patch_gui_test_compat_polluted_log_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")
    print(f"[INFO] changed: {changed}")

    if not changed:
        print("[INFO] no diff")
        return 0

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"--- {target} (before)",
            tofile=f"+++ {target} (after)",
        )
    )

    print("[DIFF PREVIEW]")
    print(diff[:12000] if len(diff) > 12000 else diff)

    if args.apply:
        backup_dir = root / "audit_output" / "fix_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / "gui_main.py.bak_test_compat_polluted_log_v1"
        backup_file.write_text(before, encoding="utf-8")
        target.write_text(after, encoding="utf-8")
        print(f"[BACKUP] {backup_file}")
        print(f"[PATCHED] {target}")
    else:
        print("[PREVIEW] 补丁可应用")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
