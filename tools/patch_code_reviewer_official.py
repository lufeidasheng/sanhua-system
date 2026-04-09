#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


MODULE_PY = r'''from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_MODULE_SINGLETON = None


class CodeReviewerModule:
    """
    三花聚顶 code_reviewer 正式最小可用版（只读审查版）
    提供：
    - code_reviewer.review_text
    - code_reviewer.review_file
    """

    name = "code_reviewer"
    version = "2.0.0"
    title = "Code Reviewer Module"

    def __init__(self, *args, **kwargs):
        self.started = False
        self.project_root = Path.cwd()

    def start(self) -> Dict[str, Any]:
        self.started = True
        return {"ok": True, "module": self.name, "status": "started"}

    def stop(self) -> Dict[str, Any]:
        self.started = False
        return {"ok": True, "module": self.name, "status": "stopped"}

    def _resolve_path(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Path:
        path_value = None
        if kwargs.get("path"):
            path_value = kwargs["path"]
        elif context and context.get("path"):
            path_value = context["path"]
        else:
            path_value = "modules/system_monitor/module.py"

        p = Path(str(path_value))
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    def _pick_text(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if kwargs.get("text"):
            return str(kwargs["text"])
        if context and context.get("text"):
            return str(context["text"])
        return ""

    def _calc_risk_level(self, issues: List[Dict[str, Any]]) -> str:
        levels = [i.get("level", "low") for i in issues]
        if "high" in levels:
            return "high"
        if "medium" in levels:
            return "medium"
        return "low"

    def _score(self, issues: List[Dict[str, Any]]) -> int:
        penalty = 0
        for item in issues:
            lv = item.get("level", "low")
            if lv == "high":
                penalty += 15
            elif lv == "medium":
                penalty += 6
            else:
                penalty += 2
        return max(0, 100 - penalty)

    def _review_text_core(self, text: str, review_target: str = "<inline>") -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        lines = text.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()

            if "eval(" in line:
                issues.append({
                    "line": idx,
                    "level": "high",
                    "code": "DANGEROUS_EVAL",
                    "message": "检测到 eval()，存在明显风险",
                })

            if re.search(r"\\bexec\\s*\\(", line):
                issues.append({
                    "line": idx,
                    "level": "high",
                    "code": "DANGEROUS_EXEC",
                    "message": "检测到 exec()，存在明显风险",
                })

            if "subprocess.run" in line and "shell=True" in line:
                issues.append({
                    "line": idx,
                    "level": "medium",
                    "code": "SHELL_TRUE",
                    "message": "检测到 subprocess.run(..., shell=True)",
                })

            if re.match(r"except\\s*:\\s*$", s):
                issues.append({
                    "line": idx,
                    "level": "medium",
                    "code": "BARE_EXCEPT",
                    "message": "检测到裸 except，异常边界不清晰",
                })

            if re.match(r"except\\s+Exception\\s*(as\\s+\\w+)?\\s*:\\s*$", s):
                issues.append({
                    "line": idx,
                    "level": "medium",
                    "code": "BROAD_EXCEPT",
                    "message": "检测到 except Exception，建议收窄异常范围",
                })

            if "TODO" in line or "FIXME" in line:
                issues.append({
                    "line": idx,
                    "level": "low",
                    "code": "TODO_MARK",
                    "message": "检测到 TODO/FIXME 标记",
                })

            if re.search(r"\\bprint\\s*\\(", line):
                issues.append({
                    "line": idx,
                    "level": "low",
                    "code": "DEBUG_PRINT",
                    "message": "检测到 print()，发布前建议确认是否保留",
                })

            if re.search(r"(password|secret|token)\\s*=", line, re.IGNORECASE):
                issues.append({
                    "line": idx,
                    "level": "medium",
                    "code": "POSSIBLE_SECRET",
                    "message": "检测到疑似敏感变量赋值",
                })

            if s == "pass":
                issues.append({
                    "line": idx,
                    "level": "low",
                    "code": "EMPTY_PASS",
                    "message": "检测到空 pass，建议确认是否有意留空",
                })

        risk_level = self._calc_risk_level(issues)
        score = self._score(issues)

        return {
            "ok": True,
            "source": "code_reviewer_module",
            "view": "review",
            "timestamp": int(time.time()),
            "target": review_target,
            "issue_count": len(issues),
            "risk_level": risk_level,
            "score": score,
            "issues": issues,
            "started": self.started,
            "summary": (
                f"review_target={review_target} | "
                f"issue_count={len(issues)} | "
                f"risk_level={risk_level} | "
                f"score={score}"
            ),
        }

    def action_review_text(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        text = self._pick_text(context=context, **kwargs)
        if not text.strip():
            return {
                "ok": False,
                "source": "code_reviewer_module",
                "view": "review_text",
                "timestamp": int(time.time()),
                "error": "empty_text",
            }

        result = self._review_text_core(text, review_target="<inline_text>")
        result["view"] = "review_text"
        return result

    def action_review_file(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        p = self._resolve_path(context=context, **kwargs)

        max_chars = kwargs.get("max_chars")
        if max_chars is None and context:
            max_chars = context.get("max_chars")
        try:
            max_chars = int(max_chars or 8000)
        except Exception:
            max_chars = 8000

        if not p.exists():
            return {
                "ok": False,
                "source": "code_reviewer_module",
                "view": "review_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "file_not_found",
            }

        if not p.is_file():
            return {
                "ok": False,
                "source": "code_reviewer_module",
                "view": "review_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": "not_a_file",
            }

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {
                "ok": False,
                "source": "code_reviewer_module",
                "view": "review_file",
                "timestamp": int(time.time()),
                "path": str(p),
                "error": str(e),
            }

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        result = self._review_text_core(text, review_target=str(p))
        result["view"] = "review_file"
        result["path"] = str(p)
        result["max_chars"] = max_chars
        result["truncated"] = truncated
        return result


def get_module_instance(*args, **kwargs) -> CodeReviewerModule:
    global _MODULE_SINGLETON
    if _MODULE_SINGLETON is None:
        _MODULE_SINGLETON = CodeReviewerModule(*args, **kwargs)
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

    _safe_register(dispatcher, "code_reviewer.review_text", module.action_review_text)
    _safe_register(dispatcher, "code_reviewer.review_file", module.action_review_file)

    _safe_register_aliases(
        dispatcher,
        "code_reviewer.review_text",
        [
            "审查代码文本",
            "评审代码文本",
        ],
    )
    _safe_register_aliases(
        dispatcher,
        "code_reviewer.review_file",
        [
            "审查代码文件",
            "评审代码文件",
            "检查代码文件",
        ],
    )

    log.info("code_reviewer 动作注册完成: code_reviewer.review_text / code_reviewer.review_file")
    return {
        "ok": True,
        "module": "code_reviewer",
        "actions": [
            "code_reviewer.review_text",
            "code_reviewer.review_file",
        ],
    }


def entry(*args, **kwargs) -> CodeReviewerModule:
    return get_module_instance(*args, **kwargs)


__all__ = [
    "CodeReviewerModule",
    "get_module_instance",
    "register_actions",
    "entry",
]
'''.strip() + "\n"


INIT_PY = r'''from __future__ import annotations

from .module import CodeReviewerModule, entry, get_module_instance, register_actions

__all__ = [
    "CodeReviewerModule",
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
    ap = argparse.ArgumentParser(description="修复 code_reviewer 为正式可注册模块")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    print("=" * 72)
    print("code_reviewer 正式模块补丁开始")
    print("=" * 72)

    write_with_backup(root, "modules/code_reviewer/module.py", MODULE_PY, backup_root)
    write_with_backup(root, "modules/code_reviewer/__init__.py", INIT_PY, backup_root)

    print("=" * 72)
    print("code_reviewer 正式模块补丁完成")
    print("=" * 72)
    print("下一步建议：")
    print(f'  python3 "{root}/tools/patch_decision_chain_whitelist_v5.py" --root "{root}"')
    print("=" * 72)


if __name__ == "__main__":
    main()
