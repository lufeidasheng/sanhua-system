
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


MODULE_PY = r'''from __future__ import annotations

import logging
import os
import platform
import socket
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class SystemControlModule:
    """
    三花聚顶 system_control 正式最小可用版（安全版）
    目标：
    1. 提供 system.health_check / system.status
    2. 暂不提供危险动作（重启/关机/网络变更）
    3. register_actions(dispatcher) 可直接被 bootstrap 调用
    """

    name = "system_control"
    version = "2.0.0"
    title = "System Control Module"

    def __init__(self, *args, **kwargs):
        self.started = False

    def start(self) -> Dict[str, Any]:
        self.started = True
        return {
            "ok": True,
            "module": self.name,
            "status": "started",
        }

    def stop(self) -> Dict[str, Any]:
        self.started = False
        return {
            "ok": True,
            "module": self.name,
            "status": "stopped",
        }

    def _base_info(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "source": "system_control_module",
            "timestamp": int(time.time()),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": socket.gethostname(),
            "cwd": os.getcwd(),
            "started": self.started,
        }

    def health_check(self) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "health_check"
        return out

    # --------------------------------------------------------
    # dispatcher actions
    # --------------------------------------------------------

    def action_health_check(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "health_check"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_status(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        out = self._base_info()
        out["view"] = "status"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out


def get_module_instance(*args, **kwargs) -> SystemControlModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = SystemControlModule(*args, **kwargs)
    return _MODULE_SINGLETON


def _safe_unregister(dispatcher: Any, action_name: str) -> None:
    try:
        existing = dispatcher.get_action(action_name) if hasattr(dispatcher, "get_action") else None
    except Exception:
        existing = None

    if existing is not None and hasattr(dispatcher, "unregister_action"):
        try:
            dispatcher.unregister_action(action_name)
        except Exception:
            pass


def _safe_register(dispatcher: Any, action_name: str, func: Any) -> None:
    _safe_unregister(dispatcher, action_name)
    dispatcher.register_action(action_name, func)


def _safe_register_aliases(dispatcher: Any, action_name: str, aliases: list[str]) -> None:
    if not aliases:
        return

    if hasattr(dispatcher, "register_aliases"):
        try:
            dispatcher.register_aliases(action_name, aliases)
            return
        except TypeError:
            pass
        except Exception:
            pass

    if hasattr(dispatcher, "register_alias"):
        for alias in aliases:
            try:
                dispatcher.register_alias(alias, action_name)
                continue
            except TypeError:
                pass
            except Exception:
                pass

            try:
                dispatcher.register_alias(action_name, alias)
            except Exception:
                pass


def register_actions(dispatcher: Any) -> Dict[str, Any]:
    module = get_module_instance()

    _safe_register(dispatcher, "system.health_check", module.action_health_check)
    _safe_register(dispatcher, "system.status", module.action_status)

    _safe_register_aliases(
        dispatcher,
        "system.health_check",
        [
            "系统健康检查",
            "健康检查",
            "检查系统健康",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "system.status",
        [
            "系统状态",
            "查看系统状态",
        ],
    )

    log.info("system_control 动作注册完成: system.health_check / system.status")
    return {
        "ok": True,
        "module": "system_control",
        "actions": ["system.health_check", "system.status"],
    }


def entry(*args, **kwargs) -> SystemControlModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "SystemControlModule",
    "get_module_instance",
    "register_actions",
    "entry",
]
'''.strip() + "\n"


INIT_PY = r'''from __future__ import annotations

from .module import SystemControlModule, entry, get_module_instance, register_actions

__all__ = [
    "SystemControlModule",
    "entry",
    "get_module_instance",
    "register_actions",
]
'''.strip() + "\n"


def write_with_backup(root: Path, rel: str, content: str, backup_root: Path) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)

    backup = backup_root / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, backup)

    path.write_text(content, encoding="utf-8")
    print(f"[PATCHED] {path}")
    if backup.exists():
        print(f"[BACKUP ] {backup}")


def main():
    ap = argparse.ArgumentParser(description="修复 system_control 为正式可注册模块")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    print("=" * 72)
    print("system_control 正式模块补丁开始")
    print("=" * 72)

    write_with_backup(root, "modules/system_control/module.py", MODULE_PY, backup_root)
    write_with_backup(root, "modules/system_control/__init__.py", INIT_PY, backup_root)

    print("=" * 72)
    print("system_control 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root}/tools/patch_decision_chain_whitelist_v2.py" --root "{root}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
