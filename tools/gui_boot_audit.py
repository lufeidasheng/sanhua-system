#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple


GUI_ALIAS_PATCH_MARK = "SANHUA_GUI_ALIAS_FORCE_PATCH_START"
AUDIO_CAPTURE_PATCH_MARK = "SANHUA_AUDIO_CAPTURE_MACOS_SPAWN_PATCH_START"


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def file_nonempty(path: Path) -> bool:
    return path.exists() and bool(safe_read(path).strip())


def load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check(path: str, ok: bool, detail: str) -> Tuple[str, bool, str]:
    return (path, ok, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description="GUI 启动专项审计")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    gui_main = root / "entry" / "gui_entry" / "gui_main.py"
    alias_base = root / "config" / "aliases.yaml"
    alias_platform = root / "config" / f"aliases.{os.sys.platform}.yaml"
    audio_capture_module = root / "modules" / "audio_capture" / "module.py"
    system_boot_report = root / "audit_output" / "system_boot_audit_report.json"

    gui_text = safe_read(gui_main)
    audio_text = safe_read(audio_capture_module)
    boot_report = load_json(system_boot_report)

    checks: List[Tuple[str, bool, str]] = []

    checks.append(check("gui_main.exists", gui_main.exists(), str(gui_main)))
    checks.append(check("aliases.base.exists", alias_base.exists(), str(alias_base)))
    checks.append(check("aliases.base.nonempty", file_nonempty(alias_base), "base aliases non-empty"))
    checks.append(check("aliases.platform.exists", alias_platform.exists(), str(alias_platform)))
    checks.append(check("audio_capture.module.exists", audio_capture_module.exists(), str(audio_capture_module)))

    checks.append(
        check(
            "gui.alias_patch.present",
            GUI_ALIAS_PATCH_MARK in gui_text,
            "gui_main 已注入 alias force patch" if GUI_ALIAS_PATCH_MARK in gui_text else "未注入",
        )
    )
    checks.append(
        check(
            "audio_capture.spawn_patch.present",
            AUDIO_CAPTURE_PATCH_MARK in audio_text,
            "audio_capture 已注入 macOS spawn 安全补丁" if AUDIO_CAPTURE_PATCH_MARK in audio_text else "未注入",
        )
    )

    summary = (boot_report.get("summary") or {})
    checks.append(
        check(
            "system_boot.official_module_count_23",
            summary.get("official_module_count") == 23,
            f"official_module_count={summary.get('official_module_count')}",
        )
    )
    checks.append(
        check(
            "system_boot.broken_module_count_0",
            summary.get("broken_module_count") == 0,
            f"broken_module_count={summary.get('broken_module_count')}",
        )
    )

    issues: List[str] = []
    warnings: List[str] = []

    if not file_nonempty(alias_base):
        issues.append("config/aliases.yaml 不存在或为空")
    if not alias_platform.exists():
        warnings.append(f"未找到平台别名文件：{alias_platform.name}（可自动补齐）")
    if GUI_ALIAS_PATCH_MARK not in gui_text:
        issues.append("GUI alias force patch 尚未注入")
    if AUDIO_CAPTURE_PATCH_MARK not in audio_text:
        issues.append("audio_capture macOS spawn 安全补丁尚未注入")

    overall = "GUI_BOOT_READY" if not issues else "GUI_BOOT_PENDING_PATCH"

    print("=" * 100)
    print("GUI BOOT AUDIT")
    print("=" * 100)
    print(f"overall : {overall}")
    print(f"root    : {root}")
    print()

    print("[checks]")
    for name, ok, detail in checks:
        flag = "✅" if ok else "⚠️"
        print(f"  {flag} {name:<36} -> {detail}")

    print()
    print("[issues]")
    if issues:
        for x in issues:
            print(f"  - {x}")
    else:
        print("  (none)")

    print()
    print("[warnings]")
    if warnings:
        for x in warnings:
            print(f"  - {x}")
    else:
        print("  (none)")

    out = {
        "ok": overall == "GUI_BOOT_READY",
        "overall": overall,
        "root": str(root),
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        "issues": issues,
        "warnings": warnings,
    }

    out_path = root / "audit_output" / "gui_boot_audit_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"json_report : {out_path}")
    print("=" * 100)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
