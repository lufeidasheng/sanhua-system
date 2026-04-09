# -*- coding: utf-8 -*-
"""
Auto-normalized module package bridge.

目的：
- 避免 __init__.py 对 entry / register_actions 做刚性导入
- 保持 package -> module.py 的兼容代理
"""

from importlib import import_module as _import_module

_module = _import_module(f"{__name__}.module")

entry = getattr(_module, "entry", None)
register_actions = getattr(_module, "register_actions", None)


def __getattr__(name):
    return getattr(_module, name)


def __dir__():
    return sorted(set(globals().keys()) | set(dir(_module)))


__all__ = ["entry", "register_actions"]
