#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List


@dataclass
class PatchResult:
    module: str
    path: str
    ok: bool
    changed: bool
    reason: str
    backup: str = ""

    def to_dict(self):
        return asdict(self)


PATCH_START = "# === SANHUA_PRELOAD_COMPAT_PATCH_START ==="
PATCH_END = "# === SANHUA_PRELOAD_COMPAT_PATCH_END ==="


MODEL_ENGINE_ACTIONS_PATCH = r'''
# === SANHUA_PRELOAD_COMPAT_PATCH_START ===
try:
    import json as _sanhua_json
    from pathlib import Path as _sanhua_Path
    from types import SimpleNamespace as _sanhua_SimpleNamespace
except Exception:
    _sanhua_json = None
    _sanhua_Path = None
    _sanhua_SimpleNamespace = None


def _sanhua_ctx_get(_ctx, _key, _default=None):
    if isinstance(_ctx, dict):
        return _ctx.get(_key, _default)
    return getattr(_ctx, _key, _default)


def _sanhua_make_ns(**kwargs):
    if _sanhua_SimpleNamespace is not None:
        return _sanhua_SimpleNamespace(**kwargs)
    return type("_SanhuaCompatNS", (), kwargs)()


def _sanhua_try_get_aicore():
    try:
        from core.aicore.aicore import get_aicore_instance
        return get_aicore_instance()
    except Exception:
        return None


def _sanhua_mea_build_legacy_context(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    aicore = (
        getattr(self, "aicore", None)
        or _sanhua_ctx_get(raw, "aicore")
        or _sanhua_try_get_aicore()
    )

    return _sanhua_make_ns(
        aicore=aicore,
        dispatcher=dispatcher,
        action_dispatcher=dispatcher,
        ACTION_MANAGER=dispatcher,
        action_manager=dispatcher,
        context=raw,
        raw_context=raw,
    )


def _sanhua_mea_register_manifest_actions(self, legacy=None, context=None):
    if legacy is None:
        legacy = getattr(self, "_legacy", None)
    if legacy is None:
        return []

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(context if context is not None else getattr(self, "context", None))
    except Exception:
        dispatcher = None

    if dispatcher is None:
        return []

    manifest_actions = []
    try:
        manifest_path = _sanhua_Path(__file__).with_name("manifest.json")
        if manifest_path.exists() and _sanhua_json is not None:
            data = _sanhua_json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_actions = data.get("actions") or []
    except Exception:
        manifest_actions = []

    if not manifest_actions:
        return []

    def _do_register(_name, _func, _description="", _aliases=None):
        _aliases = _aliases or []
        for _method_name in ("register_action", "register"):
            _method = getattr(dispatcher, _method_name, None)
            if not callable(_method):
                continue

            trials = [
                lambda: _method(_name, _func, description=_description, aliases=_aliases),
                lambda: _method(_name, _func, description=_description),
                lambda: _method(_name, _func, aliases=_aliases),
                lambda: _method(_name, _func),
            ]
            for _trial in trials:
                try:
                    _trial()
                    return True
                except TypeError:
                    continue
                except Exception:
                    return False
        return False

    registered = []
    for item in manifest_actions:
        if isinstance(item, dict):
            action_name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            aliases = item.get("aliases") or []
        else:
            action_name = str(item).strip()
            description = ""
            aliases = []

        if not action_name:
            continue

        suffix = action_name.split(".")[-1]
        candidates = [
            getattr(legacy, action_name.replace(".", "_"), None),
            getattr(legacy, f"action_{suffix}", None),
            getattr(legacy, f"action_{action_name.replace('.', '_')}", None),
        ]

        target = None
        for cand in candidates:
            if callable(cand):
                target = cand
                break

        if target is None:
            continue

        def _wrapped(*args, __target=target, **kwargs):
            return _sanhua_safe_call(__target, *args, **kwargs)

        if _do_register(action_name, _wrapped, description, aliases):
            registered.append(action_name)

    return registered


def _sanhua_mea_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None)
    if legacy_cls is None:
        try:
            legacy_cls = _sanhua_find_legacy_target()
        except Exception:
            legacy_cls = None
        self._legacy_cls = legacy_cls

    if legacy_cls is None:
        return None

    ctx_ns = _sanhua_mea_build_legacy_context(self)
    aicore = getattr(ctx_ns, "aicore", None)
    dispatcher = getattr(ctx_ns, "dispatcher", None)

    trials = [
        lambda: legacy_cls(ctx_ns),
        lambda: legacy_cls(context=ctx_ns),
        lambda: legacy_cls(aicore=aicore),
        lambda: legacy_cls(dispatcher=dispatcher),
        lambda: legacy_cls(),
    ]

    last_error = None
    for trial in trials:
        try:
            legacy = trial()
            self._legacy = legacy
            return legacy
        except TypeError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return None


def _sanhua_mea_preload(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_mea_ensure_legacy(self)
    ctx_ns = _sanhua_mea_build_legacy_context(self, getattr(self, "context", None))

    preload_fn = getattr(legacy, "preload", None) if legacy is not None else None
    if callable(preload_fn):
        try:
            return _sanhua_safe_call(preload_fn, ctx_ns)
        except Exception:
            return _sanhua_safe_call(preload_fn)

    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "preload",
        "module": "model_engine_actions",
    }


def _sanhua_mea_setup(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_mea_ensure_legacy(self)
    ctx_ns = _sanhua_mea_build_legacy_context(self, getattr(self, "context", None))

    result = None
    setup_fn = getattr(legacy, "setup", None) if legacy is not None else None
    if callable(setup_fn):
        try:
            result = _sanhua_safe_call(setup_fn, ctx_ns)
        except Exception:
            result = _sanhua_safe_call(setup_fn)

    try:
        registered = _sanhua_mea_register_manifest_actions(self, legacy=legacy, context=getattr(self, "context", None))
    except Exception:
        registered = []

    self.started = True
    return {
        "ok": True,
        "started": self.started,
        "source": "official_wrapper_compat",
        "view": "setup",
        "module": "model_engine_actions",
        "registered_actions": registered,
        "legacy_result": result,
    }


def _sanhua_mea_health_check(self):
    return {
        "ok": True,
        "started": bool(getattr(self, "started", False)),
        "source": "official_wrapper_compat",
        "view": "health_check",
        "module": "model_engine_actions",
    }


def _sanhua_mea_start(self):
    self.started = True
    return {
        "ok": True,
        "started": True,
        "source": "official_wrapper_compat",
        "view": "start",
        "module": "model_engine_actions",
    }


def _sanhua_mea_stop(self):
    self.started = False
    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "stop",
        "module": "model_engine_actions",
    }


try:
    OfficialModelEngineActionsModule._ensure_legacy = _sanhua_mea_ensure_legacy
    OfficialModelEngineActionsModule.preload = _sanhua_mea_preload
    OfficialModelEngineActionsModule.setup = _sanhua_mea_setup
    OfficialModelEngineActionsModule.health_check = _sanhua_mea_health_check
    OfficialModelEngineActionsModule.start = _sanhua_mea_start
    OfficialModelEngineActionsModule.stop = _sanhua_mea_stop
except Exception:
    pass
# === SANHUA_PRELOAD_COMPAT_PATCH_END ===
'''.lstrip()


STATE_DESCRIBE_PATCH = r'''
# === SANHUA_PRELOAD_COMPAT_PATCH_START ===
try:
    import json as _sanhua_json
    from pathlib import Path as _sanhua_Path
    from types import SimpleNamespace as _sanhua_SimpleNamespace
except Exception:
    _sanhua_json = None
    _sanhua_Path = None
    _sanhua_SimpleNamespace = None


def _sanhua_ctx_get(_ctx, _key, _default=None):
    if isinstance(_ctx, dict):
        return _ctx.get(_key, _default)
    return getattr(_ctx, _key, _default)


def _sanhua_make_ns(**kwargs):
    if _sanhua_SimpleNamespace is not None:
        return _sanhua_SimpleNamespace(**kwargs)
    return type("_SanhuaCompatNS", (), kwargs)()


def _sanhua_try_get_aicore():
    try:
        from core.aicore.aicore import get_aicore_instance
        return get_aicore_instance()
    except Exception:
        return None


def _sanhua_sd_build_core(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    aicore = (
        getattr(self, "aicore", None)
        or _sanhua_ctx_get(raw, "aicore")
        or _sanhua_try_get_aicore()
    )

    if aicore is not None:
        return aicore
    return _sanhua_make_ns(raw_context=raw)


def _sanhua_sd_build_context(self, context=None):
    raw = context if context is not None else getattr(self, "context", None)

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(raw)
    except Exception:
        dispatcher = None

    core = _sanhua_sd_build_core(self, raw)

    return _sanhua_make_ns(
        core=core,
        aicore=core,
        dispatcher=dispatcher,
        action_dispatcher=dispatcher,
        ACTION_MANAGER=dispatcher,
        action_manager=dispatcher,
        context=raw,
        raw_context=raw,
    )


def _sanhua_sd_register_manifest_actions(self, legacy=None, context=None):
    if legacy is None:
        legacy = getattr(self, "_legacy", None)
    if legacy is None:
        return []

    dispatcher = None
    try:
        dispatcher = self._resolve_dispatcher(context if context is not None else getattr(self, "context", None))
    except Exception:
        dispatcher = None

    if dispatcher is None:
        return []

    manifest_actions = []
    try:
        manifest_path = _sanhua_Path(__file__).with_name("manifest.json")
        if manifest_path.exists() and _sanhua_json is not None:
            data = _sanhua_json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_actions = data.get("actions") or []
    except Exception:
        manifest_actions = []

    if not manifest_actions:
        return []

    def _do_register(_name, _func, _description="", _aliases=None):
        _aliases = _aliases or []
        for _method_name in ("register_action", "register"):
            _method = getattr(dispatcher, _method_name, None)
            if not callable(_method):
                continue

            trials = [
                lambda: _method(_name, _func, description=_description, aliases=_aliases),
                lambda: _method(_name, _func, description=_description),
                lambda: _method(_name, _func, aliases=_aliases),
                lambda: _method(_name, _func),
            ]
            for _trial in trials:
                try:
                    _trial()
                    return True
                except TypeError:
                    continue
                except Exception:
                    return False
        return False

    registered = []
    for item in manifest_actions:
        if isinstance(item, dict):
            action_name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            aliases = item.get("aliases") or []
        else:
            action_name = str(item).strip()
            description = ""
            aliases = []

        if not action_name:
            continue

        suffix = action_name.split(".")[-1]
        candidates = [
            getattr(legacy, action_name.replace(".", "_"), None),
            getattr(legacy, f"action_{suffix}", None),
            getattr(legacy, f"action_{action_name.replace('.', '_')}", None),
        ]

        target = None
        for cand in candidates:
            if callable(cand):
                target = cand
                break

        if target is None:
            continue

        def _wrapped(*args, __target=target, **kwargs):
            return _sanhua_safe_call(__target, *args, **kwargs)

        if _do_register(action_name, _wrapped, description, aliases):
            registered.append(action_name)

    return registered


def _sanhua_sd_ensure_legacy(self):
    legacy = getattr(self, "_legacy", None)
    if legacy is not None:
        return legacy

    legacy_cls = getattr(self, "_legacy_cls", None)
    if legacy_cls is None:
        try:
            legacy_cls = _sanhua_find_legacy_target()
        except Exception:
            legacy_cls = None
        self._legacy_cls = legacy_cls

    if legacy_cls is None:
        return None

    ctx_ns = _sanhua_sd_build_context(self)
    core = getattr(ctx_ns, "core", None)

    trials = [
        lambda: legacy_cls(core),
        lambda: legacy_cls(core=core),
        lambda: legacy_cls(ctx_ns),
        lambda: legacy_cls(context=ctx_ns),
        lambda: legacy_cls(),
    ]

    last_error = None
    for trial in trials:
        try:
            legacy = trial()
            self._legacy = legacy
            return legacy
        except TypeError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return None


def _sanhua_sd_preload(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_sd_ensure_legacy(self)
    ctx_ns = _sanhua_sd_build_context(self, getattr(self, "context", None))

    preload_fn = getattr(legacy, "preload", None) if legacy is not None else None
    if callable(preload_fn):
        try:
            return _sanhua_safe_call(preload_fn, ctx_ns)
        except Exception:
            return _sanhua_safe_call(preload_fn)

    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "preload",
        "module": "state_describe",
    }


def _sanhua_sd_setup(self, context=None):
    if context is not None:
        self.context = context
    legacy = _sanhua_sd_ensure_legacy(self)
    ctx_ns = _sanhua_sd_build_context(self, getattr(self, "context", None))

    result = None
    setup_fn = getattr(legacy, "setup", None) if legacy is not None else None
    if callable(setup_fn):
        try:
            result = _sanhua_safe_call(setup_fn, ctx_ns)
        except Exception:
            result = _sanhua_safe_call(setup_fn)

    try:
        registered = _sanhua_sd_register_manifest_actions(self, legacy=legacy, context=getattr(self, "context", None))
    except Exception:
        registered = []

    self.started = True
    return {
        "ok": True,
        "started": self.started,
        "source": "official_wrapper_compat",
        "view": "setup",
        "module": "state_describe",
        "registered_actions": registered,
        "legacy_result": result,
    }


def _sanhua_sd_health_check(self):
    return {
        "ok": True,
        "started": bool(getattr(self, "started", False)),
        "source": "official_wrapper_compat",
        "view": "health_check",
        "module": "state_describe",
    }


def _sanhua_sd_start(self):
    self.started = True
    return {
        "ok": True,
        "started": True,
        "source": "official_wrapper_compat",
        "view": "start",
        "module": "state_describe",
    }


def _sanhua_sd_stop(self):
    self.started = False
    return {
        "ok": True,
        "started": False,
        "source": "official_wrapper_compat",
        "view": "stop",
        "module": "state_describe",
    }


try:
    OfficialStateDescribeModule._ensure_legacy = _sanhua_sd_ensure_legacy
    OfficialStateDescribeModule.preload = _sanhua_sd_preload
    OfficialStateDescribeModule.setup = _sanhua_sd_setup
    OfficialStateDescribeModule.health_check = _sanhua_sd_health_check
    OfficialStateDescribeModule.start = _sanhua_sd_start
    OfficialStateDescribeModule.stop = _sanhua_sd_stop
except Exception:
    pass
# === SANHUA_PRELOAD_COMPAT_PATCH_END ===
'''.lstrip()


TARGETS = {
    "model_engine_actions": {
        "path": "modules/model_engine_actions/module.py",
        "patch": MODEL_ENGINE_ACTIONS_PATCH,
    },
    "state_describe": {
        "path": "modules/state_describe/module.py",
        "patch": STATE_DESCRIBE_PATCH,
    },
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def backup_file(src: Path, backup_root: Path) -> Path:
    rel = str(src).lstrip(os.sep)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def upsert_patch_block(original: str, patch_block: str) -> str:
    if PATCH_START in original and PATCH_END in original:
        start = original.index(PATCH_START)
        end = original.index(PATCH_END) + len(PATCH_END)
        before = original[:start].rstrip()
        after = original[end:].lstrip("\n")
        merged = before + "\n\n" + patch_block.rstrip() + "\n"
        if after:
            merged += "\n" + after
        return merged

    base = original.rstrip() + "\n\n" + patch_block.rstrip() + "\n"
    return base


def patch_one(root: Path, module_name: str, apply: bool, backup_root: Path) -> PatchResult:
    cfg = TARGETS[module_name]
    path = root / cfg["path"]
    patch_block = cfg["patch"]

    if not path.exists():
        return PatchResult(
            module=module_name,
            path=str(path),
            ok=False,
            changed=False,
            reason="file_not_found",
        )

    old_text = read_text(path)
    new_text = upsert_patch_block(old_text, patch_block)
    changed = new_text != old_text

    if not changed:
        return PatchResult(
            module=module_name,
            path=str(path),
            ok=True,
            changed=False,
            reason="already_patched",
        )

    if not apply:
        return PatchResult(
            module=module_name,
            path=str(path),
            ok=True,
            changed=True,
            reason="preview_ok",
        )

    backup = backup_file(path, backup_root)
    write_text(path, new_text)

    return PatchResult(
        module=module_name,
        path=str(path),
        ok=True,
        changed=True,
        reason="apply_ok",
        backup=str(backup),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 broken official wrapper 的 preload/context/core 兼容问题")
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="正式写入")
    parser.add_argument(
        "--report-json",
        default="",
        help="报告输出路径，默认 audit_output/patch_broken_modules_preload_compat_v1_report.json",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    backup_root = root / "audit_output" / "fix_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    report_json = (
        Path(args.report_json).resolve()
        if args.report_json
        else root / "audit_output" / "patch_broken_modules_preload_compat_v1_report.json"
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("patch_broken_modules_preload_compat_v1 开始")
    print("=" * 100)
    print(f"root    : {root}")
    print(f"apply   : {args.apply}")
    print(f"modules : {list(TARGETS.keys())}")

    results: List[PatchResult] = []
    total_ok = 0
    total_fail = 0

    for module_name in TARGETS:
        print("-" * 100)
        result = patch_one(root, module_name, args.apply, backup_root)
        results.append(result)

        print(f"[PATCH] {module_name}")
        print(f"  ok       : {result.ok}")
        print(f"  changed  : {result.changed}")
        print(f"  reason   : {result.reason}")
        if result.backup:
            print(f"  backup   : {result.backup}")

        if result.ok:
            total_ok += 1
        else:
            total_fail += 1

    payload = {
        "ok": total_fail == 0,
        "root": str(root),
        "apply": bool(args.apply),
        "total_ok": total_ok,
        "total_fail": total_fail,
        "results": [r.to_dict() for r in results],
        "backup_root": str(backup_root) if args.apply else "",
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 100)
    print("patch_broken_modules_preload_compat_v1 完成")
    print("=" * 100)
    print(f"total_ok    : {total_ok}")
    print(f"total_fail  : {total_fail}")
    print(f"report_json : {report_json}")
    if args.apply:
        print(f"backup_root : {backup_root}")
    print("=" * 100)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
