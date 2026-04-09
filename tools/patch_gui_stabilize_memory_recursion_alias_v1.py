#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import difflib
import os
import re
import shutil
import sys
import py_compile
from datetime import datetime
from pathlib import Path


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def backup_file(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_path = backup_root / target.relative_to(root)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    return backup_path


def show_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def replace_function(src: str, func_name: str, new_code: str, indent: str = "") -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(indent)}def {re.escape(func_name)}\s*\(.*?(?=^{re.escape(indent)}def |^class |\Z)"
    )
    m = pattern.search(src)
    if not m:
        raise RuntimeError(f"未找到函数/方法: {func_name}")
    start, end = m.span()
    block = new_code.rstrip() + "\n\n"
    return src[:start] + block + src[end:]


def insert_before_function(src: str, anchor_func_name: str, insert_code: str, indent: str = "") -> str:
    pattern = re.compile(
        rf"(?m)^{re.escape(indent)}def {re.escape(anchor_func_name)}\s*\("
    )
    m = pattern.search(src)
    if not m:
        raise RuntimeError(f"未找到插入锚点函数: {anchor_func_name}")
    pos = m.start()
    block = insert_code.rstrip() + "\n\n"
    return src[:pos] + block + src[pos:]


def patch_gui_main(src: str) -> str:
    out = src

    # ------------------------------------------------------------------
    # 1) memory pipeline depth guard helper
    # ------------------------------------------------------------------
    if "_sanhua_gui_memory_pipeline_depth" not in out:
        insert_code = r'''
def _sanhua_gui_memory_pipeline_depth(_aicore):
    try:
        return int(getattr(_aicore, "_sanhua_gui_memory_pipeline_depth", 0) or 0)
    except Exception:
        return 0


def _sanhua_gui_memory_pipeline_enter(_aicore):
    _depth = _sanhua_gui_memory_pipeline_depth(_aicore) + 1
    try:
        setattr(_aicore, "_sanhua_gui_memory_pipeline_depth", _depth)
    except Exception:
        pass
    return _depth


def _sanhua_gui_memory_pipeline_leave(_aicore):
    _depth = max(_sanhua_gui_memory_pipeline_depth(_aicore) - 1, 0)
    try:
        setattr(_aicore, "_sanhua_gui_memory_pipeline_depth", _depth)
    except Exception:
        pass
    return _depth
'''.strip("\n")
        out = insert_before_function(out, "_sanhua_gui_mem_wrap_method", insert_code, indent="")

    # ------------------------------------------------------------------
    # 2) replace _sanhua_gui_mem_wrap_method with re-entry guard
    # ------------------------------------------------------------------
    new_wrap_method = r'''
def _sanhua_gui_mem_wrap_method(_aicore, _method_name):
    _orig = getattr(_aicore, _method_name, None)
    if not callable(_orig):
        return False

    if getattr(_orig, "_sanhua_gui_memory_wrapped", False):
        return False

    def _wrapped(_user_text, *args, **kwargs):
        # 关键：共享重入保护
        # chat -> ask / ask -> chat / 内部再次回调时，直接落回原始方法，避免无限套娃
        if _sanhua_gui_memory_pipeline_depth(_aicore) > 0:
            return _orig(_user_text, *args, **kwargs)

        _sanhua_gui_memory_pipeline_enter(_aicore)
        try:
            if not isinstance(_user_text, str):
                return _orig(_user_text, *args, **kwargs)

            _plain = _user_text.strip()
            if not _plain:
                return _orig(_user_text, *args, **kwargs)

            try:
                _sanhua_gui_mem_append_chat(_aicore, "user", _plain)
            except Exception:
                pass

            try:
                _ctx = _sanhua_gui_mem_collect_context(_aicore, _plain)
            except Exception:
                _ctx = {}

            _augmented = _sanhua_gui_mem_build_prompt(_plain, _ctx)
            _result = _orig(_augmented, *args, **kwargs)

            _reply = _sanhua_gui_mem_extract_text(_result)
            _sanitized_reply = _sanhua_gui_mem_sanitize_reply_for_writeback(
                _plain,
                _augmented,
                _result,
            )

            try:
                if _sanitized_reply.strip():
                    _sanhua_gui_mem_append_chat(_aicore, "assistant", _sanitized_reply)
                elif _reply.strip():
                    print("⚠️ GUI memory pipeline: polluted assistant reply skipped")
            except Exception:
                pass

            try:
                _summary = (_sanitized_reply or f"{_method_name}_done").strip()[:200]
                _sanhua_gui_mem_append_action(
                    _aicore,
                    f"aicore.{_method_name}",
                    "success",
                    _summary,
                )
            except Exception:
                pass

            return _result
        finally:
            _sanhua_gui_memory_pipeline_leave(_aicore)

    setattr(_wrapped, "_sanhua_gui_memory_wrapped", True)
    setattr(_wrapped, "__wrapped__", _orig)
    setattr(_aicore, _method_name, _wrapped)
    return True
'''.strip("\n")
    out = replace_function(out, "_sanhua_gui_mem_wrap_method", new_wrap_method, indent="")

    # ------------------------------------------------------------------
    # 3) local recall splitter helpers
    # ------------------------------------------------------------------
    if "_split_user_chunks" not in out:
        insert_code = r'''
_SANHUA_GUI_TRIVIAL_GREETINGS = (
    "你好",
    "您好",
    "晚上好",
    "早上好",
    "中午好",
    "下午好",
    "hi",
    "hello",
    "嗨",
    "哈喽",
)


def _sanhua_gui_is_trivial_greeting(_text):
    _plain = _sanhua_gui_mem_compact_text(_text, _limit=32)
    if not _plain:
        return False
    _plain = _plain.rstrip("，,。！？!?：:；; ").strip().lower()
    return _plain in {x.lower() for x in _SANHUA_GUI_TRIVIAL_GREETINGS}


def _split_user_chunks(_text):
    _text = str(_text or "").replace("\r", "\n").strip()
    if not _text:
        return []

    _segments = []
    for _seg in re.split(r"[\n•]+", _text):
        _seg = str(_seg or "").strip()
        if not _seg:
            continue

        # “晚上好，我是谁？” 这种复合句，优先保留核心问题
        if "，" in _seg and _seg.endswith(("？", "?")):
            _left, _right = _seg.rsplit("，", 1)
            if _sanhua_gui_is_trivial_greeting(_left):
                _seg = _right.strip()

        _seg = re.sub(r"^\s*[\-\*\d\.\)\(、:：]+\s*", "", _seg).strip()
        if _seg:
            _segments.append(_seg)

    _out = []
    _seen = set()
    for _seg in _segments:
        _seg = _sanhua_gui_mem_compact_text(_seg, _limit=88)
        if not _seg:
            continue
        if _sanhua_gui_is_trivial_greeting(_seg):
            continue
        _key = _sanhua_gui_mem_key(_seg)
        if not _key or _key in _seen:
            continue
        _seen.add(_key)
        _out.append(_seg)

    return _out
'''.strip("\n")
        out = insert_before_function(out, "_sanhua_gui_local_memory_recent_reply", insert_code, indent="")

    # ------------------------------------------------------------------
    # 4) replace _sanhua_gui_local_memory_recent_reply
    # ------------------------------------------------------------------
    new_recent_reply = r'''
def _sanhua_gui_local_memory_recent_reply(_recent, _current_user_text):
    _current_chunks = _split_user_chunks(_current_user_text)
    _current_keys = {_sanhua_gui_mem_key(x) for x in _current_chunks if str(x).strip()}

    _user_msgs = []
    _seen = set()

    for _m in (_recent or []):
        if not isinstance(_m, dict):
            continue
        if str(_m.get("role") or "").strip() != "user":
            continue

        _content = str(_m.get("content") or "").strip()
        if not _content:
            continue

        for _chunk in _split_user_chunks(_content):
            _key = _sanhua_gui_mem_key(_chunk)
            if not _key:
                continue
            if _key in _current_keys:
                continue
            if _key in _seen:
                continue

            _seen.add(_key)
            _user_msgs.append(_chunk)

    if not _user_msgs:
        return ""

    _user_msgs = _user_msgs[-3:]
    _lines = [f"{idx}. {txt}" for idx, txt in enumerate(_user_msgs, start=1)]
    return "你刚才说过：\n" + "\n".join(_lines)
'''.strip("\n")
    out = replace_function(out, "_sanhua_gui_local_memory_recent_reply", new_recent_reply, indent="")

    # ------------------------------------------------------------------
    # 5) replace MainWindow._try_load_aliases
    # ------------------------------------------------------------------
    new_try_load_aliases = r'''
    def _try_load_aliases(self):
        try:
            base, plat_file, plat = resolve_alias_files()
            disp = self.dispatcher

            if not disp:
                self.append_log("⚠️ dispatcher 不可用，跳过 aliases 加载")
                return

            existing = dispatcher_alias_count(disp)

            # 已经在启动阶段加载过，就别再误报
            if getattr(self.ctx, "_aliases_loaded", False) and existing > 0:
                self.append_log(f"🌸 aliases already loaded = {existing} (platform={plat})")
                return

            total = 0
            if base.exists():
                total += int(load_aliases_from_yaml(str(base), disp) or 0)
            if plat_file.exists():
                total += int(load_aliases_from_yaml(str(plat_file), disp) or 0)

            final_count = dispatcher_alias_count(disp)

            if total > 0 or final_count > 0:
                try:
                    setattr(self.ctx, "_aliases_loaded", True)
                except Exception:
                    pass
                self.append_log(f"🌸 aliases loaded = {max(total, final_count)} (platform={plat})")
            else:
                self.append_log(
                    f"⚠️ aliases 未加载（未找到 {base} 或 {plat_file}，或 loader 返回 0）"
                )

        except Exception as e:
            self.append_log(f"❌ alias 加载失败：{pretty_exc(e)}")
'''.strip("\n")
    out = replace_function(out, "_try_load_aliases", new_try_load_aliases, indent="    ")

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    target = root / "entry" / "gui_entry" / "gui_main.py"

    if not target.exists():
        print(f"[ERROR] target not found: {target}")
        return 2

    before = read_text(target)
    after = patch_gui_main(before)

    print("=" * 96)
    print("patch_gui_stabilize_memory_recursion_alias_v1")
    print("=" * 96)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    changed = (before != after)
    print(f"[INFO] changed: {changed}")

    diff = show_diff(before, after, f"--- {target} (before)", f"+++ {target} (after)")
    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff[:20000])
    else:
        print("[INFO] no diff")

    if not args.apply:
        try:
            tmp = root / "audit_output" / "_tmp_gui_main_preview.py"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            write_text(tmp, after)
            py_compile.compile(str(tmp), doraise=True)
            tmp.unlink(missing_ok=True)
            print("[PREVIEW] 补丁可应用，且语法通过")
        except Exception as e:
            print(f"[PREVIEW] 语法检查失败: {e}")
            return 1
        return 0

    backup = backup_file(root, target)
    write_text(target, after)
    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")

    try:
        py_compile.compile(str(target), doraise=True)
        print("[OK] 语法检查通过")
    except Exception as e:
        print(f"[ERROR] 语法检查失败: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
