#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

try:
    from utils.alias_loader import load_aliases_from_yaml
except Exception:
    load_aliases_from_yaml = None  # type: ignore


def _log(logger: Optional[Callable[[str], None]], text: str) -> None:
    if callable(logger):
        try:
            logger(text)
            return
        except Exception:
            pass
    print(text)


def resolve_alias_files(root: Optional[str] = None) -> Tuple[Path, Path, str]:
    root_path = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    platform_key = sys.platform.lower()
    base = root_path / "config" / "aliases.yaml"
    plat = root_path / "config" / f"aliases.{platform_key}.yaml"
    return base, plat, platform_key


def count_dispatcher_aliases(dispatcher: Any) -> int:
    if dispatcher is None:
        return 0

    for attr in ("aliases", "_aliases", "alias_map", "_alias_map"):
        data = getattr(dispatcher, attr, None)
        if isinstance(data, dict):
            return len(data)

    return 0


def bootstrap_aliases(
    dispatcher: Any,
    logger: Optional[Callable[[str], None]] = None,
    root: Optional[str] = None,
    skip_if_present: bool = True,
) -> int:
    if dispatcher is None:
        _log(logger, "⚠️ dispatcher 不可用，跳过 aliases 加载")
        return 0

    base, plat, platform_key = resolve_alias_files(root=root)
    existing = count_dispatcher_aliases(dispatcher)

    if skip_if_present and existing > 0:
        _log(logger, f"🌸 aliases 已就绪：{existing} 条（platform={platform_key}）")
        return existing

    if not callable(load_aliases_from_yaml):
        _log(logger, "⚠️ alias_loader 不可用，无法加载 aliases")
        return existing

    total = 0
    try:
        if base.exists():
            total += int(load_aliases_from_yaml(str(base), dispatcher) or 0)
        if plat.exists():
            total += int(load_aliases_from_yaml(str(plat), dispatcher) or 0)
    except Exception as e:
        _log(logger, f"❌ alias 加载失败：{e}")
        return count_dispatcher_aliases(dispatcher)

    final_count = count_dispatcher_aliases(dispatcher)
    if final_count > 0:
        _log(logger, f"🌸 aliases loaded = {final_count} (platform={platform_key})")
        return final_count

    _log(
        logger,
        f"⚠️ aliases 未加载（未找到 {base.name} / {plat.name}，或 loader 返回 0）",
    )
    return max(total, existing, final_count)
