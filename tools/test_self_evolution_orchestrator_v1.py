#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from pprint import pprint

from core.aicore.aicore import get_aicore_instance


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    demo_file = root / "audit_output" / "tmp_self_evolution_orchestrator_demo.py"
    demo_file.parent.mkdir(parents=True, exist_ok=True)

    original_text = (
        "def demo():\n"
        "    value = 1\n"
        "    return value\n"
    )
    demo_file.write_text(original_text, encoding="utf-8")

    aicore = get_aicore_instance()

    print("=" * 96)
    print("case_1: preview replace")
    print("=" * 96)
    result_1 = aicore.evolve_file_replace(
        path="audit_output/tmp_self_evolution_orchestrator_demo.py",
        old="value = 1",
        new="value = 2",
        user_query="测试 orchestrator preview replace",
        preview_only=True,
    )
    pprint(result_1)
    print("\nASSERT case_1 =", "PASS" if result_1.get("ok") else "FAIL")

    print("\n" + "=" * 96)
    print("case_2: apply replace ok")
    print("=" * 96)
    result_2 = aicore.evolve_file_replace(
        path="audit_output/tmp_self_evolution_orchestrator_demo.py",
        old="value = 1",
        new="value = 2",
        user_query="测试 orchestrator apply replace",
        preview_only=False,
    )
    pprint(result_2)

    now_text = demo_file.read_text(encoding="utf-8")
    case_2_ok = result_2.get("ok") and ("value = 2" in now_text)
    print("\nASSERT case_2 =", "PASS" if case_2_ok else "FAIL")

    print("\n" + "=" * 96)
    print("case_3: apply replace bad -> rollback")
    print("=" * 96)
    result_3 = aicore.evolve_file_replace(
        path="audit_output/tmp_self_evolution_orchestrator_demo.py",
        old="return value",
        new="return )",
        user_query="测试 orchestrator bad replace rollback",
        preview_only=False,
    )
    pprint(result_3)

    final_text = demo_file.read_text(encoding="utf-8")
    rollback_ok = "return value" in final_text and "return )" not in final_text
    case_3_ok = (not result_3.get("ok")) and rollback_ok
    print("\nASSERT case_3 =", "PASS" if case_3_ok else "FAIL")

    print("\n" + "=" * 96)
    print("case_4: preview append")
    print("=" * 96)
    result_4 = aicore.evolve_file_append(
        path="audit_output/tmp_self_evolution_orchestrator_demo.py",
        text="\n# preview append\n",
        user_query="测试 orchestrator preview append",
        preview_only=True,
    )
    pprint(result_4)
    print("\nASSERT case_4 =", "PASS" if result_4.get("ok") else "FAIL")

    print("\n" + "=" * 96)
    print("case_5: apply append ok")
    print("=" * 96)
    result_5 = aicore.evolve_file_append(
        path="audit_output/tmp_self_evolution_orchestrator_demo.py",
        text="\n# real append\n",
        user_query="测试 orchestrator apply append",
        preview_only=False,
    )
    pprint(result_5)

    appended_text = demo_file.read_text(encoding="utf-8")
    case_5_ok = result_5.get("ok") and "# real append" in appended_text
    print("\nASSERT case_5 =", "PASS" if case_5_ok else "FAIL")

    print("\n" + "=" * 96)
    print("FINAL =", "PASS" if all([result_1.get("ok"), case_2_ok, case_3_ok, result_4.get("ok"), case_5_ok]) else "FAIL")
    print("=" * 96)

    demo_file.write_text(original_text, encoding="utf-8")


if __name__ == "__main__":
    main()
