#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
from datetime import datetime
from pathlib import Path


SCRIPT_NAME = "patch_gui_memory_identity_guard_v1"


def hr():
    print("=" * 96)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def backup_file(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    out = backup_root / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def compile_check(target: Path, content: str) -> None:
    compile(content, str(target), "exec")


def patch_once(src: str) -> tuple[str, bool]:
    changed = False

    helper_anchor = "def _sanhua_gui_mem_push_unique(_arr, _seen, _text, _limit=160, _max_items=None):"
    helper_block = """
def _sanhua_gui_mem_identity_name_ok(_name):
    _name = str(_name or '').strip()
    if not _name:
        return False

    _bad_exact = {
        '谁', '我', '你', '他', '她', '它',
        '用户', 'user', 'unknown', 'none', 'null',
        '姓名', '名字', '名字？', '我是谁', '你是谁'
    }
    if _name.lower() in _bad_exact or _name in _bad_exact:
        return False

    if len(_name) > 24:
        return False

    _bad_parts = ('当前用户问题', '用户问题', '记忆', '摘要', 'recent', 'identity')
    if any(_x in _name for _x in _bad_parts):
        return False

    return True


def _sanhua_gui_mem_pick_identity_name(_persona, _stable_facts, _aliases):
    _persona = _persona or {}
    _stable_facts = _stable_facts or {}
    _aliases = _aliases or []

    _candidates = [
        _persona.get('name'),
        _stable_facts.get('identity.name'),
    ] + list(_aliases)

    for _c in _candidates:
        _c = _sanhua_gui_mem_compact_text(_c, _limit=24)
        if _sanhua_gui_mem_identity_name_ok(_c):
            return _c

    return ''
""".strip()

    if "def _sanhua_gui_mem_identity_name_ok(_name):" not in src:
        idx = src.find(helper_anchor)
        if idx < 0:
            raise RuntimeError("anchor_not_found: helper_anchor")
        src = src[:idx] + helper_block + "\n\n" + src[idx:]
        changed = True

    old_identity_block = """    _identity_candidate = {
        'name': _sanhua_gui_mem_compact_text(_persona.get('name'), _limit=24),
        'aliases': _aliases,
        'notes': _sanhua_gui_mem_compact_text(_persona.get('notes'), _limit=120),
        'project_focus': _project_focus,
        'stable_facts': _stable_facts,
    }"""

    new_identity_block = """    _resolved_name = _sanhua_gui_mem_pick_identity_name(_persona, _stable_facts, _aliases)

    _clean_aliases = []
    _alias_seen_2 = set()
    for _a in _aliases:
        _a = _sanhua_gui_mem_compact_text(_a, _limit=24)
        if not _sanhua_gui_mem_identity_name_ok(_a):
            continue
        _k = _sanhua_gui_mem_key(_a)
        if not _k or _k in _alias_seen_2:
            continue
        _alias_seen_2.add(_k)
        _clean_aliases.append(_a)

    if _resolved_name:
        _resolved_key = _sanhua_gui_mem_key(_resolved_name)
        _clean_aliases = [x for x in _clean_aliases if _sanhua_gui_mem_key(x) != _resolved_key]

    _identity_candidate = {
        'name': _resolved_name,
        'aliases': _clean_aliases[:3],
        'notes': _sanhua_gui_mem_compact_text(_persona.get('notes'), _limit=120),
        'project_focus': _project_focus,
        'stable_facts': _stable_facts,
    }"""

    if old_identity_block in src:
        src = src.replace(old_identity_block, new_identity_block, 1)
        changed = True

    return src, changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    hr()
    print(SCRIPT_NAME)
    hr()
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target not found")
        return 1

    before = read_text(target)
    after, changed = patch_once(before)

    try:
        compile_check(target, after)
    except Exception as e:
        print(f"[ERROR] compile failed: {e}")
        return 1

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"--- {target} (before)",
            tofile=f"+++ {target} (after)",
            n=3,
        )
    )

    print(f"[INFO] changed: {changed}")
    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff)
    else:
        print("[INFO] no diff")

    if not args.apply:
        print("[PREVIEW] 补丁可应用，且语法通过")
        hr()
        return 0

    backup = backup_file(root, target)
    write_text(target, after)
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    hr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
