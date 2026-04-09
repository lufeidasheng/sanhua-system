#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


NEW_METHOD = '''
    def _execute_action_step(
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

        tried = []

        def _output_ok(output: Any) -> tuple[bool, str | None]:
            if isinstance(output, dict) and output.get("ok") is False:
                return False, output.get("error") or output.get("reason") or "action returned ok=False"
            return True, None

        def _extract_callable() -> tuple[Optional[Any], Optional[str]]:
            # 第一优先级：从 get_action 里直接拿真实 func
            if hasattr(dispatcher, "get_action"):
                tried.append("get_action")
                try:
                    meta = dispatcher.get_action(action_name)
                except Exception:
                    meta = None

                if meta is not None:
                    for attr in ("func", "callback", "handler", "action", "callable"):
                        fn = getattr(meta, attr, None)
                        if callable(fn):
                            return fn, f"get_action({attr})"
                    if callable(meta):
                        return meta, "get_action(callable)"

            # 第二优先级：match_action
            if hasattr(dispatcher, "match_action"):
                tried.append("match_action")
                try:
                    matched = dispatcher.match_action(action_name)
                except Exception:
                    matched = None

                if callable(matched):
                    return matched, "match_action(callable)"

                if isinstance(matched, (tuple, list)) and matched:
                    fn = matched[0]
                    if callable(fn):
                        return fn, "match_action(tuple-callable)"

            return None, None

        def _invoke_callable(fn: Any) -> tuple[Any, str]:
            local_params = dict(params)
            context_value = local_params.pop("context", None)

            attempts = []

            if context_value is not None:
                attempts.append((
                    "callable(context=..., **kwargs)",
                    lambda: fn(context=context_value, **local_params),
                ))
                attempts.append((
                    "callable(positional_context, **kwargs)",
                    lambda: fn(context_value, **local_params),
                ))

            attempts.append((
                "callable(**kwargs)",
                lambda: fn(**local_params),
            ))
            attempts.append((
                "callable(kwargs_dict)",
                lambda: fn(local_params),
            ))

            if context_value is not None:
                attempts.append((
                    "callable(positional_context)",
                    lambda: fn(context_value),
                ))

            attempts.append((
                "callable()",
                lambda: fn(),
            ))

            last_type_error = None
            for label, runner in attempts:
                try:
                    return runner(), label
                except TypeError as e:
                    last_type_error = e
                    continue

            if last_type_error is not None:
                raise last_type_error
            raise RuntimeError("未找到可用调用方式")

        try:
            # ------------------------------------------------
            # 第一层：优先直调已注册动作，避免 dispatcher.execute 注入 context 造成签名冲突
            # ------------------------------------------------
            fn, bridge = _extract_callable()
            if callable(fn):
                output, invoke_mode = _invoke_callable(fn)
                ok, reason = _output_ok(output)
                return ok, {
                    "step_id": step.step_id,
                    "title": step.title,
                    "kind": step.kind,
                    "status": "ok" if ok else "failed",
                    "action_name": action_name,
                    "output": output,
                    "bridge_method": bridge,
                    "invoke_mode": invoke_mode,
                    **({"reason": reason} if reason else {}),
                }

            # ------------------------------------------------
            # 第二层：回退到 dispatcher 的显式执行接口
            # ------------------------------------------------
            for method_name in (
                "execute",
                "execute_action_and_notify",
                "call_action",
                "dispatch_action",
                "execute_action",
                "run_action",
                "trigger_action",
                "do_action",
                "dispatch",
                "call",
                "invoke",
                "run",
                "trigger",
            ):
                if not hasattr(dispatcher, method_name):
                    continue

                tried.append(method_name)
                fn2 = getattr(dispatcher, method_name)

                try:
                    output = fn2(action_name, **params)
                    ok, reason = _output_ok(output)
                    return ok, {
                        "step_id": step.step_id,
                        "title": step.title,
                        "kind": step.kind,
                        "status": "ok" if ok else "failed",
                        "action_name": action_name,
                        "output": output,
                        "bridge_method": f"{method_name}(action_name, **params)",
                        **({"reason": reason} if reason else {}),
                    }
                except TypeError:
                    try:
                        output = fn2(action_name, params)
                        ok, reason = _output_ok(output)
                        return ok, {
                            "step_id": step.step_id,
                            "title": step.title,
                            "kind": step.kind,
                            "status": "ok" if ok else "failed",
                            "action_name": action_name,
                            "output": output,
                            "bridge_method": f"{method_name}(action_name, params)",
                            **({"reason": reason} if reason else {}),
                        }
                    except TypeError:
                        try:
                            output = fn2({"action": action_name, **params})
                            ok, reason = _output_ok(output)
                            return ok, {
                                "step_id": step.step_id,
                                "title": step.title,
                                "kind": step.kind,
                                "status": "ok" if ok else "failed",
                                "action_name": action_name,
                                "output": output,
                                "bridge_method": f"{method_name}({{'action': action_name, ...}})",
                                **({"reason": reason} if reason else {}),
                            }
                        except TypeError:
                            continue

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
'''.strip("\n")


def main():
    ap = argparse.ArgumentParser(description="修补 execution_planner 动作执行桥接与结果语义")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "core2_0" / "sanhuatongyu" / "execution_planner.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    pattern = re.compile(
        r"    def _execute_action_step\((?:.|\n)*?\n    def _execute_shell_step\(",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        print("[ERROR] 未找到 _execute_action_step 替换区块")
        raise SystemExit(1)

    replacement = NEW_METHOD + "\n\n    def _execute_shell_step("
    new_text = text[:m.start()] + replacement + text[m.end():]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "core2_0" / "sanhuatongyu"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "execution_planner.py")

    target.write_text(new_text, encoding="utf-8")

    print("=" * 72)
    print("execution_planner 动作桥接/结果语义 v2 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'execution_planner.py'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
