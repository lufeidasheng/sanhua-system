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
import shutil
import time
from typing import Any, Dict, Optional

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class SystemMonitorModule:
    """
    三花聚顶 system_monitor 正式最小可用版
    目标：
    1. 提供 sysmon.status / sysmon.metrics / sysmon.health
    2. register_actions(dispatcher) 可直接被 bootstrap 调用
    3. entry 可被旧模块入口 import，不再炸包
    """

    name = "system_monitor"
    version = "2.0.0"
    title = "System Monitor Module"

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

    def health_check(self) -> Dict[str, Any]:
        snap = self._snapshot()
        return {
            "ok": True,
            "module": self.name,
            "source": "system_monitor_module",
            "started": self.started,
            "timestamp": snap["timestamp"],
            "platform": snap["platform"],
            "python": snap["python"],
        }

    def _snapshot(self) -> Dict[str, Any]:
        data = {
            "ok": True,
            "source": "system_monitor_module",
            "timestamp": int(time.time()),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cwd": os.getcwd(),
            "started": self.started,
        }

        try:
            du = shutil.disk_usage("/")
            data.update({
                "disk_total": int(du.total),
                "disk_used": int(du.used),
                "disk_free": int(du.free),
            })
        except Exception as e:
            data["disk_error"] = str(e)

        if psutil is not None:
            try:
                vm = psutil.virtual_memory()
                data.update({
                    "memory_total": int(vm.total),
                    "memory_used": int(vm.used),
                    "memory_available": int(vm.available),
                    "memory_percent": float(vm.percent),
                })
            except Exception as e:
                data["memory_error"] = str(e)

            try:
                data["cpu_percent"] = float(psutil.cpu_percent(interval=0.1))
            except Exception as e:
                data["cpu_error"] = str(e)
        else:
            data.update({
                "memory_total": None,
                "memory_used": None,
                "memory_available": None,
                "memory_percent": None,
                "cpu_percent": None,
            })

        return data

    # --------------------------------------------------------
    # dispatcher actions
    # --------------------------------------------------------

    def action_status(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        out = self._snapshot()
        out["view"] = "status"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_metrics(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        out = self._snapshot()
        out["view"] = "metrics"
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out

    def action_health(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        snap = self._snapshot()
        out = {
            "ok": True,
            "source": "system_monitor_module",
            "view": "health",
            "timestamp": snap["timestamp"],
            "platform": snap["platform"],
            "python": snap["python"],
            "started": self.started,
        }
        if context is not None:
            out["context"] = context
        if kwargs:
            out["kwargs"] = kwargs
        return out


def get_module_instance(*args, **kwargs) -> SystemMonitorModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = SystemMonitorModule(*args, **kwargs)
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

    _safe_register(dispatcher, "sysmon.status", module.action_status)
    _safe_register(dispatcher, "sysmon.metrics", module.action_metrics)
    _safe_register(dispatcher, "sysmon.health", module.action_health)

    _safe_register_aliases(
        dispatcher,
        "sysmon.status",
        [
            "系统状态",
            "查看系统状态",
            "监控状态",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "sysmon.metrics",
        [
            "系统指标",
            "监控指标",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "sysmon.health",
        [
            "系统健康",
            "监控健康",
        ],
    )

    log.info("system_monitor 动作注册完成: sysmon.status / sysmon.metrics / sysmon.health")
    return {
        "ok": True,
        "module": "system_monitor",
        "actions": ["sysmon.status", "sysmon.metrics", "sysmon.health"],
    }


def entry(*args, **kwargs) -> SystemMonitorModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "SystemMonitorModule",
    "get_module_instance",
    "register_actions",
    "entry",
]
'''.strip() + "\n"


INIT_PY = r'''from __future__ import annotations

from .module import SystemMonitorModule, entry, get_module_instance, register_actions

__all__ = [
    "SystemMonitorModule",
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
    ap = argparse.ArgumentParser(description="修复 system_monitor 为正式可注册模块")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    print("=" * 72)
    print("system_monitor 正式模块补丁开始")
    print("=" * 72)

    write_with_backup(root, "modules/system_monitor/module.py", MODULE_PY, backup_root)
    write_with_backup(root, "modules/system_monitor/__init__.py", INIT_PY, backup_root)

    print("=" * 72)
    print("system_monitor 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root}/tools/test_system_monitor_official.py"')
    print("=" * 72)


if __name__ == "__main__":
    main()
