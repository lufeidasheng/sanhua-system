#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from pprint import pprint

from core.aicore.aicore import get_aicore_instance


MODULE_FILES = [
    "modules/system_monitor/module.py",
    "modules/system_control/module.py",
    "modules/code_reader/module.py",
    "modules/code_inserter/module.py",
    "modules/code_reviewer/module.py",
]


def normalize_actions(raw):
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.keys())
    if isinstance(raw, (list, tuple, set)):
        out = []
        for x in raw:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                name = x.get("name") or x.get("action")
                if name:
                    out.append(str(name))
            else:
                out.append(str(x))
        return out
    return [str(raw)]


class DispatcherCompat:
    def __init__(self, real_dispatcher):
        self._real = real_dispatcher

    def __getattr__(self, item):
        return getattr(self._real, item)

    def register_action(self, name, func=None, *args, **kwargs):
        """
        兼容旧模块的 register_action(name, func, description=..., parameters=..., aliases=...)
        当前真实 dispatcher 只吃最小签名：register_action(name, func)
        aliases 单独补。
        """
        if func is None:
            raise TypeError("register_action 需要至少 name, func")

        result = self._real.register_action(name, func)

        aliases = kwargs.pop("aliases", None)
        if aliases:
            if hasattr(self._real, "register_aliases"):
                try:
                    self._real.register_aliases(name, aliases)
                except Exception:
                    pass
            elif hasattr(self._real, "register_alias"):
                for alias in aliases:
                    try:
                        self._real.register_alias(alias, name)
                    except Exception:
                        pass

        return result


def load_module_from_file(root: Path, rel: str):
    path = root / rel
    if not path.exists():
        raise FileNotFoundError(path)

    mod_name = "bootstrap_" + rel.replace("/", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建 spec: {rel}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def call_register_actions(mod, dispatcher):
    if not hasattr(mod, "register_actions"):
        return False, "register_actions not found"

    fn = getattr(mod, "register_actions")
    if not callable(fn):
        return False, "register_actions not callable"

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
            return True, "register_actions()"
        else:
            fn(dispatcher)
            return True, "register_actions(dispatcher)"
    except Exception as e:
        return False, str(e)


def main():
    root = Path(__file__).resolve().parents[1]
    aicore = get_aicore_instance()
    dispatcher = aicore._resolve_dispatcher()
    compat = DispatcherCompat(dispatcher)

    print("=" * 88)
    print("before compat bootstrap")
    print("=" * 88)
    before = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(before))
    for x in before:
        print(x)

    results = []

    for rel in MODULE_FILES:
        try:
            mod = load_module_from_file(root, rel)
        except Exception as e:
            results.append({
                "module_file": rel,
                "ok": False,
                "message": f"load failed: {e}",
            })
            continue

        ok, msg = call_register_actions(mod, compat)
        results.append({
            "module_file": rel,
            "ok": ok,
            "message": msg,
        })

    print("\n" + "=" * 88)
    print("compat bootstrap results")
    print("=" * 88)
    pprint(results)

    print("\n" + "=" * 88)
    print("after compat bootstrap")
    print("=" * 88)
    after = sorted(set(normalize_actions(dispatcher.list_actions())))
    print("count =", len(after))
    for x in after:
        if any(k in x.lower() for k in ("sysmon", "system", "memory", "ai.", "health", "status")):
            print(x)


if __name__ == "__main__":
    main()
