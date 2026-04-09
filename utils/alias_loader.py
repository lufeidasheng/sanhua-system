#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.alias_loader

目标：
- 只提供函数，不要在 import 时执行任何注册（避免重复导入导致多次执行）
- 兼容两种 aliases.yaml 结构：
  1) list 结构（你的现状）：[{name, keywords, function}]
  2) dict 结构：{alias: action_name}
- 幂等：同一路径只加载一次（挂到 dispatcher 上做缓存）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


def _ensure_loaded_set(dispatcher) -> set:
    s = getattr(dispatcher, "_sanhua_alias_loaded_paths", None)
    if not isinstance(s, set):
        s = set()
        setattr(dispatcher, "_sanhua_alias_loaded_paths", s)
    return s


def _as_list(x) -> List[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i).strip() for i in x if str(i).strip()]
    if isinstance(x, str):
        x = x.strip()
        return [x] if x else []
    return [str(x).strip()]


def load_aliases_from_yaml(yaml_path: str, dispatcher) -> int:
    """
    加载 aliases.yaml 并注册到 dispatcher
    返回：本次新增注册的 alias 数量（幂等：同文件重复调用返回 0）
    """
    if not dispatcher:
        return 0

    p = Path(yaml_path).expanduser().resolve()
    if not p.exists():
        return 0

    loaded = _ensure_loaded_set(dispatcher)
    key = str(p)
    if key in loaded:
        return 0

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or None

    added = 0

    # 结构 A：list（你的当前格式）
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            action = (item.get("function") or item.get("action") or item.get("name") or "").strip()
            keywords = _as_list(item.get("keywords") or item.get("alias") or item.get("aliases"))
            if not action or not keywords:
                continue

            # 注意：这里不强依赖“动作已注册”，先把 alias 挂上
            # 只要后续动作注册进 dispatcher，match_action 就能生效。
            if hasattr(dispatcher, "register_alias"):
                dispatcher.register_alias(keywords, action)
            elif hasattr(dispatcher, "register_aliases"):
                dispatcher.register_aliases({action: keywords})
            else:
                # dispatcher 不支持 alias：直接跳过
                continue

            added += len(keywords)

    # 结构 B：dict（alias -> action）
    elif isinstance(data, dict):
        # 转成 action -> [alias...]
        action_map: Dict[str, List[str]] = {}
        for alias, action in data.items():
            a = str(alias).strip()
            n = str(action).strip()
            if not a or not n:
                continue
            action_map.setdefault(n, []).append(a)

        if hasattr(dispatcher, "register_aliases"):
            dispatcher.register_aliases(action_map)
            added = sum(len(v) for v in action_map.values())
        elif hasattr(dispatcher, "register_alias"):
            for act, aliases in action_map.items():
                dispatcher.register_alias(aliases, act)
            added = sum(len(v) for v in action_map.values())

    else:
        # 其他格式不处理
        added = 0

    loaded.add(key)
    return added


# 兼容旧命名：有些入口写的是 load_aliases_yaml
def load_aliases_yaml(yaml_path: str, dispatcher) -> int:
    return load_aliases_from_yaml(yaml_path, dispatcher)
