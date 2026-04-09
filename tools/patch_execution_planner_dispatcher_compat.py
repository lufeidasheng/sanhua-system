#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def safe_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def backup_file(src: Path, backup_root: Path, root: Path) -> Path:
    rel = src.relative_to(root)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


OLD = """    def _execute_action_step(
        self,
        step: PlanStep,
        dispatcher: Optional[Any],
        dispatch_context: Dict[str, Any],
    ) -> tuple[bool, Dict[str, Any]]:
        if dispatcher is None:
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "reason": "未提供 dispatcher，无法执行 action 步骤",
            }

        action_name = step.action_name
        params = dict(step.params or {})
        if dispatch_context:
            params.setdefault("context", dispatch_context)

        try:
            if hasattr(dispatcher, "call_action"):
                output = dispatcher.call_action(action_name, **params)
            elif hasattr(dispatcher, "dispatch_action"):
                output = dispatcher.dispatch_action(action_name, **params)
            elif hasattr(dispatcher, "execute_action"):
                output = dispatcher.execute_action(action_name, **params)
            else:
                return False, {
                    "step_id": step.step_id,
                    "title": step.title,
                    "kind": step.kind,
                    "status": "failed",
                    "reason": "dispatcher 不支持 call_action/dispatch_action/execute_action",
                }

            return True, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "ok",
                "action_name": action_name,
                "output": output,
            }
        except Exception as exc:
            log.exception("执行 action 步骤失败: %s", step.action_name)
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "action_name": action_name,
                "reason": str(exc),
            }
"""

NEW = """    def _execute_action_step(
        self,
        step: PlanStep,
        dispatcher: Optional[Any],
        dispatch_context: Dict[str, Any],
    ) -> tuple[bool, Dict[str, Any]]:
        if dispatcher is None:
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "reason": "未提供 dispatcher，无法执行 action 步骤",
            }

        action_name = step.action_name
        params = dict(step.params or {})
        if dispatch_context:
            params.setdefault("context", dispatch_context)

        def _try_call(obj: Any, method_name: str, *args, **kwargs):
            if not hasattr(obj, method_name):
                raise AttributeError(method_name)
            fn = getattr(obj, method_name)
            return fn(*args, **kwargs)

        tried = []

        try:
            # 第一层：最明确的 action API
            for method_name in (
                "call_action",
                "dispatch_action",
                "execute_action",
                "run_action",
                "trigger_action",
                "do_action",
            ):
                if hasattr(dispatcher, method_name):
                    tried.append(method_name)
                    try:
                        output = _try_call(dispatcher, method_name, action_name, **params)
                        return True, {
                            "step_id": step.step_id,
                            "title": step.title,
                            "kind": step.kind,
                            "status": "ok",
                            "action_name": action_name,
                            "output": output,
                            "bridge_method": method_name,
                        }
                    except TypeError:
                        # 兼容部分接口只收一个 dict 的情况
                        output = _try_call(dispatcher, method_name, action_name, params)
                        return True, {
                            "step_id": step.step_id,
                            "title": step.title,
                            "kind": step.kind,
                            "status": "ok",
                            "action_name": action_name,
                            "output": output,
                            "bridge_method": method_name,
                        }

            # 第二层：较泛化的 dispatch/call/invoke/run
            for method_name in (
                "dispatch",
                "call",
                "invoke",
                "run",
                "trigger",
            ):
                if hasattr(dispatcher, method_name):
                    tried.append(method_name)
                    try:
                        output = _try_call(dispatcher, method_name, action_name, **params)
                        return True, {
                            "step_id": step.step_id,
                            "title": step.title,
                            "kind": step.kind,
                            "status": "ok",
                            "action_name": action_name,
                            "output": output,
                            "bridge_method": method_name,
                        }
                    except TypeError:
                        try:
                            output = _try_call(dispatcher, method_name, action_name, params)
                            return True, {
                                "step_id": step.step_id,
                                "title": step.title,
                                "kind": step.kind,
                                "status": "ok",
                                "action_name": action_name,
                                "output": output,
                                "bridge_method": method_name,
                            }
                        except TypeError:
                            output = _try_call(dispatcher, method_name, {"action": action_name, **params})
                            return True, {
                                "step_id": step.step_id,
                                "title": step.title,
                                "kind": step.kind,
                                "status": "ok",
                                "action_name": action_name,
                                "output": output,
                                "bridge_method": method_name,
                            }

            # 第三层：match_action -> callable
            if hasattr(dispatcher, "match_action"):
                tried.append("match_action")
                matched = dispatcher.match_action(action_name)
                if callable(matched):
                    try:
                        output = matched(**params)
                    except TypeError:
                        output = matched(params)
                    return True, {
                        "step_id": step.step_id,
                        "title": step.title,
                        "kind": step.kind,
                        "status": "ok",
                        "action_name": action_name,
                        "output": output,
                        "bridge_method": "match_action(callable)",
                    }

                if isinstance(matched, (tuple, list)) and matched:
                    fn = matched[0]
                    if callable(fn):
                        try:
                            output = fn(**params)
                        except TypeError:
                            output = fn(params)
                        return True, {
                            "step_id": step.step_id,
                            "title": step.title,
                            "kind": step.kind,
                            "status": "ok",
                            "action_name": action_name,
                            "output": output,
                            "bridge_method": "match_action(tuple-callable)",
                        }

            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "action_name": action_name,
                "reason": "dispatcher 未匹配到可用执行接口",
                "tried_methods": tried,
                "dispatcher_type": str(type(dispatcher)),
            }

        except Exception as exc:
            log.exception("执行 action 步骤失败: %s", step.action_name)
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "action_name": action_name,
                "reason": str(exc),
                "tried_methods": tried,
                "dispatcher_type": str(type(dispatcher)),
            }
"""


def main():
    ap = argparse.ArgumentParser(description="增强 execution_planner 的 dispatcher 兼容桥接")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "core2_0" / "sanhuatongyu" / "execution_planner.py"

    if not target.exists():
        print(f"[ERROR] 找不到文件：{target}")
        raise SystemExit(1)

    original = safe_read(target)
    if OLD not in original:
        print("[SKIP] 未找到预期旧代码块，未自动修改。")
        raise SystemExit(0)

    patched = original.replace(OLD, NEW, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_file(target, backup_root, root)

    safe_write(target, patched)

    print("=" * 72)
    print("execution_planner dispatcher 兼容补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup}")
    print("=" * 72)


if __name__ == "__main__":
    main()
