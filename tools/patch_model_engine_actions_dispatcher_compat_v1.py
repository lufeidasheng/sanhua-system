#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import py_compile
import shutil
import time
from pathlib import Path


HELPER_BLOCK = r'''
# === SANHUA_MODEL_ENGINE_DISPATCHER_COMPAT_START ===

def _sanhua_dispatcher_register_action(dispatcher, action_name, func, **kwargs):
    """
    兼容不同版本 dispatcher.register_action / register 的签名差异。
    目标：
    - 允许 legacy 模块继续声明 module_name / description / aliases
    - 避免因为旧签名参数导致 setup 直接炸掉
    """
    if dispatcher is None:
        raise RuntimeError("dispatcher is None")

    errors = []

    register_fn = getattr(dispatcher, "register_action", None)
    if callable(register_fn):
        trials = [
            lambda: register_fn(action_name, func, **kwargs),
            lambda: register_fn(action_name, func),
            lambda: register_fn(name=action_name, func=func, **kwargs),
            lambda: register_fn(name=action_name, func=func),
            lambda: register_fn(name=action_name, action=func, **kwargs),
            lambda: register_fn(name=action_name, action=func),
        ]
        for trial in trials:
            try:
                return trial()
            except TypeError as e:
                errors.append(e)
            except Exception:
                raise

    register_fn = getattr(dispatcher, "register", None)
    if callable(register_fn):
        trials = [
            lambda: register_fn(action_name, func, **kwargs),
            lambda: register_fn(action_name, func),
            lambda: register_fn(name=action_name, func=func, **kwargs),
            lambda: register_fn(name=action_name, func=func),
            lambda: register_fn(name=action_name, action=func, **kwargs),
            lambda: register_fn(name=action_name, action=func),
        ]
        for trial in trials:
            try:
                return trial()
            except TypeError as e:
                errors.append(e)
            except Exception:
                raise

    if errors:
        raise errors[-1]
    raise RuntimeError("dispatcher has no register_action/register method")


def _sanhua_mea_is_event_bus_not_ready_error(exc: Exception) -> bool:
    text = str(exc or "")
    return ("事件总线未初始化" in text) or ("init_event_bus" in text)


def _sanhua_mea_register_actions_direct(self, legacy):
    """
    当 legacy.setup() 因 dispatcher 签名不兼容失败时，直接兜底注册核心动作。
    """
    ctx = getattr(self, "context", None)
    dispatcher = None

    if hasattr(self, "_resolve_dispatcher"):
        try:
            dispatcher = self._resolve_dispatcher(ctx)
        except Exception:
            dispatcher = None

    if dispatcher is None:
        dispatcher = getattr(self, "dispatcher", None)

    if dispatcher is None:
        raise RuntimeError("model_engine_actions: dispatcher unavailable")

    registered = []

    candidates = [
        ("model.list", "action_list_models"),
        ("model.switch", "action_switch_model"),
        ("model.current", "action_current_model"),
    ]

    for action_name, method_name in candidates:
        fn = getattr(legacy, method_name, None)
        if callable(fn):
            _sanhua_dispatcher_register_action(
                dispatcher,
                action_name,
                fn,
                module_name="model_engine_actions",
            )
            registered.append(action_name)

    return {
        "ok": True,
        "registered": registered,
        "count": len(registered),
        "mode": "direct_register_fallback",
    }


def _sanhua_mea_preload_runtime_compat(self):
    legacy = _sanhua_mea_ensure_legacy(self)
    preload_fn = getattr(legacy, "preload", None)
    if not callable(preload_fn):
        self._sanhua_preload_degraded = False
        self._sanhua_preload_reason = "no_preload"
        return {"ok": True, "reason": "no_preload"}

    ctx_ns = None
    build_ctx = globals().get("_sanhua_mea_build_context_ns")
    if callable(build_ctx):
        try:
            ctx_ns = build_ctx(self)
        except Exception:
            ctx_ns = getattr(self, "context", None)
    else:
        ctx_ns = getattr(self, "context", None)

    try:
        result = _sanhua_safe_call(preload_fn, ctx_ns)
        self._sanhua_preload_degraded = False
        self._sanhua_preload_reason = None
        return result
    except Exception as e:
        if _sanhua_mea_is_event_bus_not_ready_error(e):
            self._sanhua_preload_degraded = True
            self._sanhua_preload_reason = str(e)
            return {
                "ok": True,
                "degraded": True,
                "reason": str(e),
            }
        raise


def _sanhua_mea_setup_runtime_compat(self):
    legacy = _sanhua_mea_ensure_legacy(self)
    setup_fn = getattr(legacy, "setup", None)

    if not callable(setup_fn):
        fallback = _sanhua_mea_register_actions_direct(self, legacy)
        self._sanhua_setup_mode = "direct_register_fallback"
        return fallback

    ctx_ns = None
    build_ctx = globals().get("_sanhua_mea_build_context_ns")
    if callable(build_ctx):
        try:
            ctx_ns = build_ctx(self)
        except Exception:
            ctx_ns = getattr(self, "context", None)
    else:
        ctx_ns = getattr(self, "context", None)

    try:
        result = _sanhua_safe_call(setup_fn, ctx_ns)
        self._sanhua_setup_mode = "legacy_setup"
        return result
    except Exception as e:
        text = str(e or "")
        if ("register_action() got an unexpected keyword argument" in text) or ("module_name" in text):
            fallback = _sanhua_mea_register_actions_direct(self, legacy)
            self._sanhua_setup_mode = "direct_register_fallback"
            return fallback
        raise


def _sanhua_mea_health_check_runtime_compat(self):
    return {
        "ok": True,
        "module": "model_engine_actions",
        "degraded": bool(getattr(self, "_sanhua_preload_degraded", False)),
        "preload_reason": getattr(self, "_sanhua_preload_reason", None),
        "setup_mode": getattr(self, "_sanhua_setup_mode", None),
    }


try:
    OfficialModelEngineActionsModule.preload = _sanhua_mea_preload_runtime_compat
    OfficialModelEngineActionsModule.setup = _sanhua_mea_setup_runtime_compat
    OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check_runtime_compat
except Exception:
    pass

# === SANHUA_MODEL_ENGINE_DISPATCHER_COMPAT_END ===
'''.strip() + "\n"


def backup_file(src: Path, backup_root: Path) -> Path:
    rel = str(src).lstrip("/")
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def patch_text(text: str) -> tuple[str, bool]:
    changed = False
    new_text = text

    marker = "# === SANHUA_MODEL_ENGINE_DISPATCHER_COMPAT_START ==="
    if marker not in new_text:
        anchor = "# === SANHUA_OFFICIAL_WRAPPER_START ==="
        if anchor in new_text:
            new_text = new_text.replace(anchor, HELPER_BLOCK + "\n" + anchor, 1)
            changed = True
        else:
            new_text += "\n\n" + HELPER_BLOCK
            changed = True

    old_call = "dispatcher.register_action("
    new_call = "_sanhua_dispatcher_register_action(dispatcher, "
    if old_call in new_text:
        new_text = new_text.replace(old_call, new_call)
        changed = True

    # 把旧绑定强制替换成 runtime compat 版本
    rebinding_pairs = [
        (
            "OfficialModelEngineActionsModule.preload = _sanhua_mea_preload",
            "OfficialModelEngineActionsModule.preload = _sanhua_mea_preload_runtime_compat",
        ),
        (
            "OfficialModelEngineActionsModule.setup = _sanhua_mea_setup",
            "OfficialModelEngineActionsModule.setup = _sanhua_mea_setup_runtime_compat",
        ),
        (
            "OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check",
            "OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check_runtime_compat",
        ),
    ]

    for old, new in rebinding_pairs:
        if old in new_text:
            new_text = new_text.replace(old, new)
            changed = True

    return new_text, changed


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 model_engine_actions 的 dispatcher / preload 兼容问题")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "model_engine_actions" / "module.py"

    print("=" * 100)
    print("patch_model_engine_actions_dispatcher_compat_v1")
    print("=" * 100)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

    if not target.exists():
        print(f"[ERROR] 文件不存在: {target}")
        return 2

    old_text = target.read_text(encoding="utf-8")
    new_text, changed = patch_text(old_text)

    if not changed:
        print("[SKIP] 未发现可应用变更，或补丁已存在")
        print("=" * 100)
        return 0

    if not args.apply:
        print("[PREVIEW] 补丁可应用")
        print("=" * 100)
        return 0

    backup_root = root / "audit_output" / "fix_backups" / time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_file(target, backup_root)

    target.write_text(new_text, encoding="utf-8")

    try:
        py_compile.compile(str(target), doraise=True)
    except Exception as e:
        shutil.copy2(backup_path, target)
        print(f"[ERROR] py_compile 失败，已回滚: {e}")
        print(f"[ROLLBACK] {backup_path}")
        print("=" * 100)
        return 3

    print(f"[BACKUP] {backup_path}")
    print(f"[PATCHED] {target}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
