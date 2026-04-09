#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import sys
import time
from pathlib import Path


def log(msg: str = "") -> None:
    print(msg)


def backup_file(src: Path, backup_root: Path) -> Path:
    rel = str(src).lstrip("/")
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


PATCH_BLOCK = r'''
def _sanhua_mea_build_context_proxy(self):
    from types import SimpleNamespace

    raw = getattr(self, "context", None)
    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    data = {}

    if isinstance(raw, dict):
        data.update(raw)
    elif raw is not None:
        for name in (
            "aicore",
            "dispatcher",
            "action_dispatcher",
            "ACTION_MANAGER",
            "action_manager",
            "root",
            "project_root",
            "config",
            "settings",
        ):
            if hasattr(raw, name):
                try:
                    data[name] = getattr(raw, name)
                except Exception:
                    pass

    if dispatcher is not None:
        data.setdefault("dispatcher", dispatcher)
        data.setdefault("action_dispatcher", dispatcher)
        data.setdefault("ACTION_MANAGER", dispatcher)
        data.setdefault("action_manager", dispatcher)

    owner_aicore = getattr(self, "aicore", None)
    if owner_aicore is not None:
        data.setdefault("aicore", owner_aicore)

    # 最低保真兜底，避免 legacy 初始化时直接炸
    data.setdefault("aicore", data.get("aicore"))
    data.setdefault("dispatcher", data.get("dispatcher"))
    data.setdefault("action_dispatcher", data.get("action_dispatcher", data.get("dispatcher")))
    data.setdefault("ACTION_MANAGER", data.get("ACTION_MANAGER", data.get("dispatcher")))
    data.setdefault("action_manager", data.get("action_manager", data.get("dispatcher")))

    return SimpleNamespace(**data)


def _sanhua_mea_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None) or _sanhua_find_legacy_target()
    if legacy_cls is None:
        self._legacy = None
        return None

    proxy = _sanhua_mea_build_context_proxy(self)
    raw = getattr(self, "context", None)
    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    last_error = None
    trials = []

    # 优先喂 proxy，兼容 legacy 里直接 context.aicore 的写法
    trials.append(lambda: legacy_cls(proxy))
    trials.append(lambda: legacy_cls(context=proxy))

    # 再尝试原始 context
    if raw is not None:
        trials.append(lambda: legacy_cls(raw))
        trials.append(lambda: legacy_cls(context=raw))

    # 再尝试最小上下文
    mini_ctx = proxy
    trials.append(lambda: legacy_cls(context=mini_ctx))
    trials.append(lambda: legacy_cls(mini_ctx))

    # 极限兜底
    trials.append(lambda: legacy_cls())

    for trial in trials:
        try:
            legacy = trial()
            self._legacy = legacy
            return legacy
        except Exception as e:
            last_error = e
            continue

    raise last_error


'''

PATTERN = re.compile(
    r"def _sanhua_mea_ensure_legacy\(self\):\n.*?(?=^def _sanhua_mea_preload\()",
    re.S | re.M,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 model_engine_actions wrapper 的 context 兼容")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "model_engine_actions" / "module.py"
    if not target.exists():
        log(f"[ERROR] 文件不存在: {target}")
        return 2

    old_text = target.read_text(encoding="utf-8")
    if "_sanhua_mea_ensure_legacy" not in old_text:
        log("[ERROR] 未找到 _sanhua_mea_ensure_legacy，无法补丁")
        return 3

    new_text, count = PATTERN.subn(PATCH_BLOCK, old_text, count=1)
    if count != 1:
        log("[ERROR] 替换 _sanhua_mea_ensure_legacy 失败")
        return 4

    if new_text == old_text:
        log("[SKIP] 文件无变化")
        return 0

    log("=" * 100)
    log("patch_model_engine_actions_context_compat_v1")
    log("=" * 100)
    log(f"root   : {root}")
    log(f"apply  : {args.apply}")
    log(f"target : {target}")

    if not args.apply:
        log("[PREVIEW] 补丁可应用")
        return 0

    backup_root = root / "audit_output" / "fix_backups" / time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_file(target, backup_root)

    target.write_text(new_text, encoding="utf-8")
    try:
        py_compile.compile(str(target), doraise=True)
    except Exception as e:
        log(f"[ERROR] py_compile 失败: {e}")
        log(f"[ROLLBACK] 从备份恢复: {backup_path}")
        shutil.copy2(backup_path, target)
        return 5

    log(f"[BACKUP] {backup_path}")
    log(f"[PATCHED] {target}")
    log("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
