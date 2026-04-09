#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
import py_compile
import shutil
from datetime import datetime
from pathlib import Path


def build_prompt_builder_function() -> str:
    s1 = repr("请把下面这些系统记忆当作高优先级参考事实。\n")
    s2 = repr("它们用于回答与用户身份、历史对话、刚才说过的话、长期偏好相关的问题。\n")
    s3 = repr("如果无关就忽略，不要硬编。\n\n")

    lines = [
        "def _sanhua_gui_mem_build_prompt(_user_text, _ctx):",
        "    if not isinstance(_ctx, dict):",
        "        return _user_text",
        "",
        "    _lines = []",
        "    _identity = _ctx.get('identity') or {}",
        "    _recent = _ctx.get('recent_messages') or []",
        "    _matches = _ctx.get('matches') or []",
        "",
        "    if _identity:",
        "        _name = str(_identity.get('name') or '').strip()",
        "        _aliases = _identity.get('aliases') or []",
        "        _notes = str(_identity.get('notes') or '').strip()",
        "        _project_focus = _identity.get('project_focus') or []",
        "        _stable_facts = _identity.get('stable_facts') or {}",
        "",
        "        _lines.append('【稳定身份记忆】')",
        "        if _name:",
        "            _lines.append(f'- 用户名：{_name}')",
        "        if _aliases:",
        "            _lines.append(f\"- 别名：{', '.join(str(x) for x in _aliases if str(x).strip())}\")",
        "        if _project_focus:",
        "            _lines.append(f\"- 项目重点：{', '.join(str(x) for x in _project_focus if str(x).strip())}\")",
        "        if _notes:",
        "            _lines.append(f'- 备注：{_notes}')",
        "        for _k, _v in _stable_facts.items():",
        "            if str(_v).strip():",
        "                _lines.append(f'- {_k}: {_v}')",
        "",
        "    if _recent:",
        "        _lines.append('【最近会话】')",
        "        for _item in _recent[-8:]:",
        "            _role = _item.get('role', 'unknown')",
        "            _content = _item.get('content', '')",
        "            if _content:",
        "                _lines.append(f'- {_role}: {_content}')",
        "",
        "    if _matches:",
        "        _lines.append('【相关记忆命中】')",
        "        for _idx, _text in enumerate(_matches[:5], start=1):",
        "            if _text:",
        "                _lines.append(f'- 命中{_idx}: {_text}')",
        "",
        "    if not _lines:",
        "        return _user_text",
        "",
        "    _memory_block = '\\n'.join(_lines).strip()",
        "    return (",
        f"        {s1}",
        f"        {s2}",
        f"        {s3}",
        "        f\"{_memory_block}\\n\\n\"",
        "        f\"当前用户问题：\\n{_user_text}\"",
        "    )",
        "",
    ]
    return "\n".join(lines)


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    backup = backup_root / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    return backup


def replace_function_block(text: str) -> tuple[str, bool]:
    start_sig = "def _sanhua_gui_mem_build_prompt(_user_text, _ctx):"
    next_sig = "def _sanhua_gui_mem_append_chat(_aicore, _role, _content):"

    start = text.find(start_sig)
    if start < 0:
        return text, False

    end = text.find(next_sig, start)
    if end < 0:
        return text, False

    new_func = build_prompt_builder_function()
    new_text = text[:start] + new_func + text[end:]
    return new_text, True


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 GUI memory pipeline 的 prompt builder 语法块")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print("=" * 96)
    print("repair_gui_memory_prompt_builder_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print(f"[ERROR] 文件不存在: {target}")
        return 2

    before = target.read_text(encoding="utf-8")
    after, changed = replace_function_block(before)

    if not changed:
        print("[ERROR] 未找到目标函数或结束锚点")
        return 3

    diff_text = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{target} (before)",
            tofile=f"{target} (after-patch)",
            lineterm="",
        )
    )

    print("[DIFF PREVIEW]")
    print(diff_text[:12000] if diff_text else "(none)")

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        return 0

    backup = make_backup(root, target)
    target.write_text(after, encoding="utf-8")

    try:
        py_compile.compile(str(target), doraise=True)
    except Exception as e:
        print(f"[ERROR] 写入后语法校验失败: {e}")
        print("[ROLLBACK] 正在回滚")
        target.write_text(before, encoding="utf-8")
        return 4

    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
