#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


BOOTSTRAP_CODE = r'''
def _wire_action_bootstrap_support(aicore: Any) -> Any:
    """
    给 AICore 单例挂载“最小动作注册引导”能力。
    目标：
    - 让 get_aicore_instance() 拿到的 ACTION_MANAGER 不再是空表
    - 不依赖 GUI 全启动
    - 先把 ai.* / sysmon.* / system.* / memory.* 这类关键动作尽量补起来
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_action_bootstrap_support_wired", False):
        return aicore

    def _normalize_actions(raw):
        if raw is None:
            return []
        if isinstance(raw, dict):
            return list(raw.keys())
        if isinstance(raw, (list, tuple, set)):
            out = []
            for item in raw:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("action")
                    if name:
                        out.append(str(name))
                else:
                    out.append(str(item))
            return out
        return [str(raw)]

    def _bootstrap_action_registry(self, force: bool = False) -> dict:
        import importlib
        import inspect
        from pathlib import Path

        dispatcher = self._resolve_dispatcher() if hasattr(self, "_resolve_dispatcher") else None
        if dispatcher is None:
            return {
                "ok": False,
                "reason": "dispatcher_not_ready",
                "count_before": 0,
                "count_after": 0,
                "details": [],
            }

        def _list_count():
            try:
                return len(set(_normalize_actions(dispatcher.list_actions())))
            except Exception:
                return 0

        count_before = _list_count()
        details = []

        if count_before > 0 and not force:
            return {
                "ok": True,
                "reason": "dispatcher_already_has_actions",
                "count_before": count_before,
                "count_after": count_before,
                "details": [],
            }

        try:
            if hasattr(dispatcher, "set_context"):
                dispatcher.set_context({"source": "aicore.bootstrap_action_registry"})
        except Exception:
            pass

        # 1) ai.* 导入即注册
        try:
            importlib.import_module("core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp")
            details.append({"step": "import_ai_actions", "ok": True})
        except Exception as e:
            details.append({"step": "import_ai_actions", "ok": False, "error": str(e)})

        # 2) 尝试入口 register_actions(dispatcher)
        for mod_name in ("entry.gui_main", "entry.gui_entry.gui_main"):
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "register_actions") and callable(getattr(mod, "register_actions")):
                    mod.register_actions(dispatcher)
                    details.append({"step": f"{mod_name}.register_actions", "ok": True})
                else:
                    details.append({"step": f"{mod_name}.register_actions", "ok": False, "error": "not_found"})
            except Exception as e:
                details.append({"step": f"{mod_name}.register_actions", "ok": False, "error": str(e)})

        # 3) 尝试关键模块 register_actions
        safe_modules = (
            "modules.system_monitor.module",
            "modules.system_control.module",
            "modules.code_reader.module",
            "modules.code_executor.module",
            "modules.code_inserter.module",
            "modules.code_reviewer.module",
            "modules.logbook.module",
        )

        for mod_name in safe_modules:
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:
                details.append({"step": mod_name, "ok": False, "error": f"import failed: {e}"})
                continue

            if not hasattr(mod, "register_actions") or not callable(getattr(mod, "register_actions")):
                details.append({"step": mod_name, "ok": False, "error": "register_actions not found"})
                continue

            fn = getattr(mod, "register_actions")
            try:
                sig = inspect.signature(fn)
                params = [
                    p for p in sig.parameters.values()
                    if p.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                ]
                if len(params) == 0:
                    fn()
                    details.append({"step": mod_name, "ok": True, "mode": "register_actions()"})
                else:
                    fn(dispatcher)
                    details.append({"step": mod_name, "ok": True, "mode": "register_actions(dispatcher)"})
            except Exception as e:
                details.append({"step": mod_name, "ok": False, "error": str(e)})

        # 4) aliases
        try:
            from utils.alias_loader import load_aliases_from_yaml
            project_root = Path(__file__).resolve().parents[2]
            alias_path = project_root / "config" / "aliases.yaml"
            if alias_path.exists():
                n = load_aliases_from_yaml(str(alias_path), dispatcher)
                details.append({"step": "aliases", "ok": True, "count": int(n or 0)})
            else:
                details.append({"step": "aliases", "ok": False, "error": "config/aliases.yaml not found"})
        except Exception as e:
            details.append({"step": "aliases", "ok": False, "error": str(e)})

        count_after = _list_count()

        return {
            "ok": count_after > 0,
            "reason": "bootstrapped" if count_after > 0 else "still_empty",
            "count_before": count_before,
            "count_after": count_after,
            "details": details,
        }

    if not hasattr(aicore, "_bootstrap_action_registry"):
        try:
            setattr(aicore, "_bootstrap_action_registry", types.MethodType(_bootstrap_action_registry, aicore))
        except Exception as e:
            _safe_log("warning", "绑定 _bootstrap_action_registry 失败: %s", e)

    try:
        aicore._action_bootstrap_support_wired = True
    except Exception:
        pass

    return aicore
'''.strip()


def main():
    ap = argparse.ArgumentParser(description="给 core/aicore/aicore.py 注入动作引导能力")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    anchor = "def get_aicore_instance(*args, **kwargs):"
    if BOOTSTRAP_CODE not in text:
        idx = text.find(anchor)
        if idx == -1:
            print("[ERROR] anchor not found")
            raise SystemExit(1)
        text = text[:idx] + BOOTSTRAP_CODE + "\n\n\n" + text[idx:]

    old = """            # 给实例挂建议闭环支持
            _AICORE_SINGLETON = _wire_decision_support(_AICORE_SINGLETON)
"""
    new = """            # 给实例挂建议闭环支持
            _AICORE_SINGLETON = _wire_decision_support(_AICORE_SINGLETON)

            # 给实例挂动作引导支持
            _AICORE_SINGLETON = _wire_action_bootstrap_support(_AICORE_SINGLETON)

            # 如果 dispatcher 还是空，主动做一次最小动作引导
            try:
                if hasattr(_AICORE_SINGLETON, "_bootstrap_action_registry"):
                    _AICORE_SINGLETON._bootstrap_action_registry(force=False)
            except Exception:
                pass
"""
    if old in text and new not in text:
        text = text.replace(old, new, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "aicore.py")

    target.write_text(text, encoding="utf-8")
    print("=" * 72)
    print("aicore 动作引导补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'aicore.py'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
