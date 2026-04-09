#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    demo_file = root / "audit_output" / "tmp_self_evolution_demo.py"
    demo_file.parent.mkdir(parents=True, exist_ok=True)

    original_text = (
        "def demo():\n"
        "    x = 1\n"
        "    return x\n"
    )
    demo_file.write_text(original_text, encoding="utf-8")

    aicore = get_aicore_instance()

    print("=" * 96)
    print("case_1: 正常 patch + 验证通过")
    print("=" * 96)

    result_ok = aicore.safe_apply_change_set(
        operations=[
            {
                "path": "audit_output/tmp_self_evolution_demo.py",
                "op": "replace_text",
                "old": "x = 1",
                "new": "x = 2",
            }
        ],
        reason="case_1_apply_ok",
        validation_checks=[
            {"kind": "file_exists", "path": "audit_output/tmp_self_evolution_demo.py"},
            {"kind": "text_contains", "path": "audit_output/tmp_self_evolution_demo.py", "needle": "x = 2"},
            {"kind": "syntax_file", "path": "audit_output/tmp_self_evolution_demo.py"},
        ],
        dry_run=False,
    )
    pprint(result_ok)

    current_text = demo_file.read_text(encoding="utf-8")
    print("\nASSERT case_1 =", "PASS" if (result_ok.get("ok") and "x = 2" in current_text) else "FAIL")

    print("\n" + "=" * 96)
    print("case_2: 非法 patch + 验证失败自动回滚")
    print("=" * 96)

    result_bad = aicore.safe_apply_change_set(
        operations=[
            {
                "path": "audit_output/tmp_self_evolution_demo.py",
                "op": "replace_text",
                "old": "return x",
                "new": "return )",
            }
        ],
        reason="case_2_apply_bad_should_rollback",
        validation_checks=[
            {"kind": "syntax_file", "path": "audit_output/tmp_self_evolution_demo.py"},
        ],
        dry_run=False,
    )
    pprint(result_bad)

    after_bad_text = demo_file.read_text(encoding="utf-8")
    rollback_ok = bool((result_bad.get("rollback") or {}).get("ok"))
    restored_ok = "return x" in after_bad_text and "return )" not in after_bad_text

    print("\nASSERT case_2 =", "PASS" if (not result_bad.get("ok") and rollback_ok and restored_ok) else "FAIL")

    # 最后恢复原始文本，避免脏状态
    demo_file.write_text(original_text, encoding="utf-8")


if __name__ == "__main__":
    main()
