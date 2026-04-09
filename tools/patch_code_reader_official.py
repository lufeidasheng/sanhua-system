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
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class CodeReaderModule:
    """
    三花聚顶 code_reader 正式最小可用版（安全读取版）
    目标：
    1. 提供 code_reader.exists / code_reader.read_file / code_reader.list_dir
    2. register_actions(dispatcher) 可直接被 bootstrap 调用
    3. 不做写入，只做安全读取
    """

    name = "code_reader"
    version = "2.0.0"
    title = "Code Reader Module"

    def __init__(self, *args, **kwargs):
        self.started = False
        self.project_root = Path.cwd()

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

    def _resolve_path(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Path:
        path_value = None

        if "path" in kwargs and kwargs["path"]:
            path_value = kwargs["path"]
        elif context and context.get("path"):
            path_value = context.get("path")
        else:
            path_value = "config/global.yaml"

        p = Path(str(path_value))
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    def action_exists(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "exists",
            "timestamp": int(time.time()),
            "path": str(p),
            "exists": p.exists(),
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "started": self.started,
        }

    def action_read_file(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        max_chars = kwargs.get("max_chars")
        if max_chars is None and context:
            max_chars = context.get("max_chars")
        try:
            max_chars = int(max_chars or 4000)
        except Exception:
            max_chars = 4000

        if not p.exists():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "file_not_found",
            }

        if not p.is_file():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "not_a_file",
            }

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "read_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": str(e),
            }

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "read_file",
            "timestamp": int(time.time()),
            "path": str(p),
            "exists": True,
            "truncated": truncated,
            "max_chars": max_chars,
            "content": text,
            "started": self.started,
        }

    def action_list_dir(
        self,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)
        limit = kwargs.get("limit")
        if limit is None and context:
            limit = context.get("limit")
        try:
            limit = int(limit or 50)
        except Exception:
            limit = 50

        if not p.exists():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "path_not_found",
            }

        if not p.is_dir():
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "not_a_dir",
            }

        try:
            entries = []
            for child in sorted(p.iterdir(), key=lambda x: x.name)[:limit]:
                entries.append({
                    "name": child.name,
                    "is_file": child.is_file(),
                    "is_dir": child.is_dir(),
                })
        except Exception as e:
            return {
                "ok": False,
                "source": "code_reader_module",
                "view": "list_dir",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": str(e),
            }

        return {
            "ok": True,
            "source": "code_reader_module",
            "view": "list_dir",
            "timestamp": int(time.time()),
            "path": str(p),
            "count": len(entries),
            "entries": entries,
            "limit": limit,
            "started": self.started,
        }


def get_module_instance(*args, **kwargs) -> CodeReaderModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = CodeReaderModule(*args, **kwargs)
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

    _safe_register(dispatcher, "code_reader.exists", module.action_exists)
    _safe_register(dispatcher, "code_reader.read_file", module.action_read_file)
    _safe_register(dispatcher, "code_reader.list_dir", module.action_list_dir)

    _safe_register_aliases(
        dispatcher,
        "code_reader.exists",
        [
            "文件是否存在",
            "检查文件是否存在",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "code_reader.read_file",
        [
            "读取文件",
            "查看文件内容",
            "读取配置文件",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "code_reader.list_dir",
        [
            "列出目录",
            "查看目录内容",
        ],
    )

    log.info("code_reader 动作注册完成: code_reader.exists / code_reader.read_file / code_reader.list_dir")
    return {
        "ok": True,
        "module": "code_reader",
        "actions": [
            "code_reader.exists",
            "code_reader.read_file",
            "code_reader.list_dir",
        ],
    }


def entry(*args, **kwargs) -> CodeReaderModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "CodeReaderModule",
    "get_module_instance",
    "register_actions",
    "entry",
]
'''.strip() + "\n"


INIT_PY = r'''from __future__ import annotations

from .module import CodeReaderModule, entry, get_module_instance, register_actions

__all__ = [
    "CodeReaderModule",
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
    ap = argparse.ArgumentParser(description="修复 code_reader 为正式可注册模块")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    print("=" * 72)
    print("code_reader 正式模块补丁开始")
    print("=" * 72)

    write_with_backup(root, "modules/code_reader/module.py", MODULE_PY, backup_root)
    write_with_backup(root, "modules/code_reader/__init__.py", INIT_PY, backup_root)

    print("=" * 72)
    print("code_reader 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root}/tools/patch_decision_chain_whitelist_v4.py" --root "{root}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
