#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import time
from pathlib import Path


PATCH_MARK = "SANHUA_GUI_ALIAS_FORCE_PATCH_START"


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def backup_copy(src: Path, backup_root: Path) -> Path:
    dst = backup_root / src.relative_to(src.anchor if src.is_absolute() else Path("."))
    if src.is_absolute():
        rel = str(src).lstrip(os.sep)
        dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def make_diff(old: str, new: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after-patch)",
            lineterm="",
        )
    )


def build_patch_block() -> str:
    return r'''

# === SANHUA_GUI_ALIAS_FORCE_PATCH_START ===
try:
    import sys as _sanhua_sys
    from pathlib import Path as _SanhuaPath

    def _sanhua_gui_root():
        return _SanhuaPath(__file__).resolve().parents[2]

    def _sanhua_yaml_load(path):
        if not path.exists():
            return {}
        try:
            import yaml
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception as _e:
            print(f"⚠️ alias yaml load failed: {path} -> {_e}")
            return {}

    def _sanhua_flatten_alias_map(data):
        alias_map = {}

        if not isinstance(data, dict):
            return alias_map

        # 兼容 1：{alias: action}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                alias_map[k] = v

        # 兼容 2：{"aliases": {...}}
        nested = data.get("aliases")
        if isinstance(nested, dict):
            for k, v in nested.items():
                if isinstance(k, str) and isinstance(v, str):
                    alias_map[k] = v

        # 兼容 3：{"actions":[{"name":"x","aliases":["a","b"]}]}
        actions = data.get("actions")
        if isinstance(actions, list):
            for item in actions:
                if not isinstance(item, dict):
                    continue
                action_name = item.get("action") or item.get("name")
                aliases = item.get("aliases") or []
                if isinstance(action_name, str):
                    for alias in aliases:
                        if isinstance(alias, str):
                            alias_map[alias] = action_name

        return alias_map

    def _sanhua_collect_aliases():
        root = _sanhua_gui_root()
        platform_key = _sanhua_sys.platform
        base_path = root / "config" / "aliases.yaml"
        platform_path = root / "config" / f"aliases.{platform_key}.yaml"

        base_data = _sanhua_yaml_load(base_path)
        plat_data = _sanhua_yaml_load(platform_path)

        alias_map = {}
        alias_map.update(_sanhua_flatten_alias_map(base_data))
        alias_map.update(_sanhua_flatten_alias_map(plat_data))
        return alias_map, base_path, platform_path, platform_key

    def _sanhua_find_dispatcher():
        for _name in ("ACTION_MANAGER", "action_manager", "dispatcher"):
            _obj = globals().get(_name)
            if _obj is not None:
                return _obj
        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER as _ACTION_MANAGER
            if _ACTION_MANAGER is not None:
                return _ACTION_MANAGER
        except Exception:
            pass
        return None

    def _sanhua_register_aliases_into_dispatcher(dispatcher, alias_map):
        if dispatcher is None or not alias_map:
            return 0

        registered = 0

        if hasattr(dispatcher, "register_aliases"):
            try:
                dispatcher.register_aliases(alias_map)
                return len(alias_map)
            except Exception as _e:
                print(f"⚠️ register_aliases failed: {_e}")

        if hasattr(dispatcher, "register_alias"):
            for alias, action in alias_map.items():
                try:
                    dispatcher.register_alias(alias, action)
                    registered += 1
                except Exception:
                    continue
            if registered:
                return registered

        # 兜底：如果 dispatcher 里有 alias map，就直接写入
        for attr in ("aliases", "_aliases", "alias_map", "_alias_map"):
            target = getattr(dispatcher, attr, None)
            if isinstance(target, dict):
                target.update(alias_map)
                return len(alias_map)

        return registered

    _SANHUA_OLD_LOAD_ALIASES = globals().get("_load_aliases")

    def _load_aliases(*args, **kwargs):
        old_count = 0
        if callable(_SANHUA_OLD_LOAD_ALIASES):
            try:
                old_count = _SANHUA_OLD_LOAD_ALIASES(*args, **kwargs) or 0
            except Exception as _e:
                print(f"⚠️ aliases old loader failed: {_e}")

        if old_count:
            return old_count

        alias_map, base_path, platform_path, platform_key = _sanhua_collect_aliases()
        dispatcher = _sanhua_find_dispatcher()
        count = _sanhua_register_aliases_into_dispatcher(dispatcher, alias_map)

        if count > 0:
            print(f"🌸 aliases force loaded = {count} (platform={platform_key})")
        else:
            print(
                "⚠️ aliases force load failed "
                f"(base={base_path.exists()} platform={platform_path.exists()} size={len(alias_map)})"
            )
        return count

except Exception as _sanhua_gui_alias_patch_error:
    print(f"⚠️ gui alias force patch init failed: {_sanhua_gui_alias_patch_error}")
# === SANHUA_GUI_ALIAS_FORCE_PATCH_END ===
'''


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 GUI aliases 启动加载链")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    ap.add_argument("--report-json", default="", help="报告输出路径")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"
    alias_base = root / "config" / "aliases.yaml"
    alias_platform = root / "config" / f"aliases.{sys.platform}.yaml"

    if not target.exists():
        print(f"[ERROR] gui_main 不存在: {target}")
        return 2

    old = safe_read(target)
    changed = False
    new = old

    notes = []

    if PATCH_MARK not in old:
        new = old.rstrip() + "\n" + build_patch_block().strip("\n") + "\n"
        changed = True
        notes.append("已追加 GUI alias force patch")
    else:
        notes.append("SKIP: 已存在 GUI alias force patch")

    platform_file_created = False
    if alias_base.exists() and not alias_platform.exists():
        notes.append(f"将补齐平台 alias 文件: {alias_platform.name}")
        if args.apply:
            alias_platform.write_text(alias_base.read_text(encoding="utf-8"), encoding="utf-8")
            platform_file_created = True
            notes.append(f"已创建 {alias_platform.name}")

    diff_text = make_diff(old, new, target)
    out_path = (
        Path(args.report_json).resolve()
        if args.report_json
        else root / "audit_output" / "patch_gui_alias_bootstrap_v1_report.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backup_root = None
    if args.apply and changed:
        backup_root = root / "audit_output" / "fix_backups" / time.strftime("%Y%m%d_%H%M%S")
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / "entry" / "gui_entry" / "gui_main.py"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
        write_text(target, new)

    report = {
        "ok": True,
        "root": str(root),
        "apply": bool(args.apply),
        "target": str(target),
        "changed": changed,
        "platform_file_created": platform_file_created,
        "notes": notes,
        "diff_preview": diff_text[:20000],
        "backup_root": str(backup_root) if backup_root else None,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 100)
    print("patch_gui_alias_bootstrap_v1")
    print("=" * 100)
    print(f"root    : {root}")
    print(f"apply   : {args.apply}")
    print(f"changed : {changed}")
    for n in notes:
        print(f"note    : {n}")
    if diff_text:
        print("-" * 100)
        print(diff_text[:8000])
    print("-" * 100)
    print(f"report_json : {out_path}")
    if backup_root:
        print(f"backup_root : {backup_root}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
