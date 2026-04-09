#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import time
from pathlib import Path


HELPER_BLOCK = r'''
# === SANHUA_MODEL_ENGINE_COMPAT_START ===
class _SanhuaNullModelEngine:
    """
    当 AICore 上没有标准 model_engine 属性时的降级兼容对象。
    目标：
    - 让 model_engine_actions 至少能 preload/setup 通过
    - current_model / list_models 之类动作可安全返回
    - 不阻塞 GUI 主启动链
    """

    def __init__(self):
        self.active_model_path = None
        self.available_models = []
        self.degraded = True
        self.reason = "aicore.model_engine_missing"

    def list_models(self):
        return list(self.available_models)

    def current_model(self):
        return self.active_model_path

    def get_current_model(self):
        return self.active_model_path

    def set_active_model(self, model_path):
        self.active_model_path = model_path
        if model_path and model_path not in self.available_models:
            self.available_models.append(model_path)
        return True

    def switch_model(self, model_path):
        return self.set_active_model(model_path)

    def ensure_ready(self):
        return True

    def health_check(self):
        return {
            "ok": True,
            "degraded": True,
            "reason": self.reason,
            "active_model_path": self.active_model_path,
            "available_models": list(self.available_models),
        }

    def __getattr__(self, name):
        def _fallback(*args, **kwargs):
            return {
                "ok": False,
                "reason": f"null_model_engine_method_not_available:{name}",
                "name": name,
            }
        return _fallback


def _sanhua_me_getattr_any(obj, *names):
    if obj is None:
        return None

    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj.get(name) is not None:
                return obj.get(name)
        return None

    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return None


def _sanhua_resolve_model_engine_from_context(context):
    """
    按多条路径解析模型引擎：
    1. context.aicore.model_engine
    2. context.aicore 的替代引擎字段
    3. context 本身携带的替代引擎字段
    4. 全局 get_aicore_instance()
    5. 最终返回 _SanhuaNullModelEngine
    """
    engine_field_candidates = (
        "model_engine",
        "_model_engine",
        "llm_engine",
        "engine",
        "model_manager",
        "inference_engine",
        "backend_engine",
    )

    aicore = _sanhua_me_getattr_any(context, "aicore")
    if aicore is not None:
        engine = _sanhua_me_getattr_any(aicore, *engine_field_candidates)
        if engine is not None:
            try:
                if getattr(aicore, "model_engine", None) is None:
                    setattr(aicore, "model_engine", engine)
            except Exception:
                pass
            return engine

    engine = _sanhua_me_getattr_any(context, *engine_field_candidates)
    if engine is not None:
        return engine

    try:
        from core.aicore.aicore import get_aicore_instance
        ai = get_aicore_instance()
    except Exception:
        ai = None

    if ai is not None:
        engine = _sanhua_me_getattr_any(ai, *engine_field_candidates)
        if engine is not None:
            try:
                if getattr(ai, "model_engine", None) is None:
                    setattr(ai, "model_engine", engine)
            except Exception:
                pass
            return engine

    return _SanhuaNullModelEngine()

# === SANHUA_MODEL_ENGINE_COMPAT_END ===
'''.lstrip()


def backup_file(src: Path, backup_root: Path) -> Path:
    rel = str(src).lstrip("/")
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 model_engine_actions 对 aicore.model_engine 的硬依赖")
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--apply", action="store_true", help="正式写入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "modules" / "model_engine_actions" / "module.py"

    if not target.exists():
        print(f"[ERROR] 文件不存在: {target}")
        return 2

    text = target.read_text(encoding="utf-8")

    old_patterns = [
        r"self\.engine\s*:\s*ModelEngine\s*=\s*context\.aicore\.model_engine",
        r"self\.engine\s*=\s*context\.aicore\.model_engine",
    ]

    replaced = False
    new_text = text

    for pattern in old_patterns:
        if re.search(pattern, new_text):
            new_text = re.sub(
                pattern,
                "self.engine: ModelEngine = _sanhua_resolve_model_engine_from_context(context)",
                new_text,
                count=1,
            )
            replaced = True
            break

    if not replaced:
        if "_sanhua_resolve_model_engine_from_context(context)" in new_text:
            print("=" * 100)
            print("patch_model_engine_actions_model_engine_compat_v1")
            print("=" * 100)
            print(f"root   : {root}")
            print(f"apply  : {args.apply}")
            print(f"target : {target}")
            print("[SKIP] 已存在 model_engine 兼容解析逻辑")
            print("=" * 100)
            return 0
        print("[ERROR] 未找到目标赋值语句，补丁无法命中")
        return 3

    if "SANHUA_MODEL_ENGINE_COMPAT_START" not in new_text:
        anchor = "# === SANHUA_OFFICIAL_WRAPPER_START ==="
        if anchor in new_text:
            new_text = new_text.replace(anchor, HELPER_BLOCK + "\n" + anchor, 1)
        else:
            import_lines = re.findall(r"^(?:from\s+[^\n]+\s+import\s+[^\n]+|import\s+[^\n]+)\n", new_text, flags=re.M)
            if import_lines:
                last_import = import_lines[-1]
                idx = new_text.rfind(last_import)
                insert_pos = idx + len(last_import)
                new_text = new_text[:insert_pos] + "\n" + HELPER_BLOCK + "\n" + new_text[insert_pos:]
            else:
                new_text = HELPER_BLOCK + "\n" + new_text

    print("=" * 100)
    print("patch_model_engine_actions_model_engine_compat_v1")
    print("=" * 100)
    print(f"root   : {root}")
    print(f"apply  : {args.apply}")
    print(f"target : {target}")

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
        return 4

    print(f"[BACKUP] {backup_path}")
    print(f"[PATCHED] {target}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
