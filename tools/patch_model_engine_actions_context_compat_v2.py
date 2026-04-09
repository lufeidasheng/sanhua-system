#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import py_compile
import re
import shutil
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
def _sanhua_mea_get_global_aicore():
    try:
        from core.aicore.aicore import get_aicore_instance
        ai = get_aicore_instance()
        if ai is not None:
            return ai
    except Exception:
        pass
    return None


def _sanhua_mea_resolve_dispatcher_from_any(obj):
    if obj is None:
        return None

    names = ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager")

    if isinstance(obj, dict):
        for name in names:
            val = obj.get(name)
            if val is not None:
                return val
        return None

    for name in names:
        if hasattr(obj, name):
            try:
                val = getattr(obj, name)
                if val is not None:
                    return val
            except Exception:
                pass
    return None


def _sanhua_mea_resolve_aicore_from_any(obj):
    if obj is None:
        return None

    if isinstance(obj, dict):
        val = obj.get("aicore")
        if val is not None:
            return val
        return None

    if hasattr(obj, "aicore"):
        try:
            val = getattr(obj, "aicore")
            if val is not None:
                return val
        except Exception:
            pass

    return None


def _sanhua_mea_build_context_proxy(self):
    from types import SimpleNamespace

    raw = getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    if dispatcher is None:
        dispatcher = _sanhua_mea_resolve_dispatcher_from_any(raw)

    if dispatcher is None:
        dispatcher = getattr(self, "dispatcher", None)

    aicore = getattr(self, "aicore", None)
    if aicore is None:
        aicore = _sanhua_mea_resolve_aicore_from_any(raw)

    if aicore is None:
        aicore = _sanhua_mea_get_global_aicore()

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
            "memory_manager",
            "prompt_memory_bridge",
        ):
            if hasattr(raw, name):
                try:
                    data[name] = getattr(raw, name)
                except Exception:
                    pass

    if aicore is not None:
        data["aicore"] = aicore

    if dispatcher is not None:
        data["dispatcher"] = dispatcher
        data["action_dispatcher"] = dispatcher
        data["ACTION_MANAGER"] = dispatcher
        data["action_manager"] = dispatcher

    data.setdefault("root", str(getattr(self, "root", "")) or data.get("root") or "")
    data.setdefault("project_root", data.get("root") or "")

    return SimpleNamespace(**data)


def _sanhua_mea_context_candidates(self):
    from types import SimpleNamespace

    raw = getattr(self, "context", None)
    proxy = _sanhua_mea_build_context_proxy(self)

    out = []

    # 1) 最优先：带真实 aicore 的 proxy
    out.append(proxy)

    # 2) 原始 context（如果有）
    if raw is not None:
        out.append(raw)

    # 3) 极简 proxy：只保留最关键字段
    mini = SimpleNamespace(
        aicore=getattr(proxy, "aicore", None),
        dispatcher=getattr(proxy, "dispatcher", None),
        action_dispatcher=getattr(proxy, "action_dispatcher", None),
        ACTION_MANAGER=getattr(proxy, "ACTION_MANAGER", None),
        action_manager=getattr(proxy, "action_manager", None),
        root=getattr(proxy, "root", ""),
        project_root=getattr(proxy, "project_root", ""),
    )
    out.append(mini)

    return out


def _sanhua_mea_instantiate_legacy(legacy_cls, ctx):
    import inspect

    last_error = None

    try:
        init_sig = inspect.signature(legacy_cls.__init__)
        params = [p for p in init_sig.parameters.values() if p.name != "self"]
    except Exception:
        params = []

    has_context_kw = any(p.name == "context" for p in params)
    has_dispatcher_kw = any(p.name == "dispatcher" for p in params)
    allow_positional = bool(params)

    dispatcher = _sanhua_mea_resolve_dispatcher_from_any(ctx)

    trials = []

    if has_context_kw and has_dispatcher_kw:
        trials.append(lambda: legacy_cls(context=ctx, dispatcher=dispatcher))

    if has_context_kw:
        trials.append(lambda: legacy_cls(context=ctx))

    if allow_positional:
        trials.append(lambda: legacy_cls(ctx))

    # 最后只保留一个“最小但仍带 context”的方案
    if has_dispatcher_kw:
        trials.append(lambda: legacy_cls(context=ctx, dispatcher=None))

    for trial in trials:
        try:
            return trial()
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError("legacy instantiate failed: no usable constructor path")


def _sanhua_mea_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None) or _sanhua_find_legacy_target()
    if legacy_cls is None:
        self._legacy = None
        return None

    last_error = None

    for ctx in _sanhua_mea_context_candidates(self):
        try:
            legacy = _sanhua_mea_instantiate_legacy(legacy_cls, ctx)
            self._legacy = legacy
            return legacy
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError("legacy init failed: no context candidate worked")


'''

PATTERN = re.compile(
    r"def _sanhua_mea_build_context_proxy\(self\):\n.*?(?=^def _sanhua_mea_preload\(self\):)",
    re.S | re.M,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 model_engine_actions wrapper 的 context 兼容 v2")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "model_engine_actions" / "module.py"
    if not target.exists():
        log(f"[ERROR] 文件不存在: {target}")
        return 2

    old_text = target.read_text(encoding="utf-8")

    if "def _sanhua_mea_build_context_proxy(self):" not in old_text:
        log("[ERROR] 未找到 _sanhua_mea_build_context_proxy，无法打 v2 补丁")
        return 3

    new_text, count = PATTERN.subn(PATCH_BLOCK, old_text, count=1)
    if count != 1:
        log("[ERROR] 替换目标 block 失败")
        return 4

    if new_text == old_text:
        log("[SKIP] 文件无变化")
        return 0

    log("=" * 100)
    log("patch_model_engine_actions_context_compat_v2")
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
        shutil.copy2(backup_path, target)
        log(f"[ROLLBACK] 已回滚: {backup_path}")
        return 5

    log(f"[BACKUP] {backup_path}")
    log(f"[PATCHED] {target}")
    log("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
