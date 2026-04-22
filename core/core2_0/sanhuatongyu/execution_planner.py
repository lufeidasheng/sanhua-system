from __future__ import annotations

import inspect
import logging
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.core2_0.sanhuatongyu.decision_arbiter import ArbiterDecision
from core.core2_0.sanhuatongyu.suggestion_interpreter import InterpretationResult, SuggestionItem

log = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class PlanStep:
    step_id: str
    title: str
    kind: str  # action / shell / manual / checkpoint
    action_name: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    command: Optional[str] = None
    manual_instruction: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    status: str = "planned"
    dry_run_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionPlan:
    plan_id: str
    summary: str
    steps: List[PlanStep] = field(default_factory=list)
    executable: bool = False
    blocked_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "summary": self.summary,
            "steps": [s.to_dict() for s in self.steps],
            "executable": self.executable,
            "blocked_reasons": self.blocked_reasons,
        }


@dataclass
class ExecutionResult:
    plan_id: str
    mode: str  # dry_run / execute
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 规划器
# ============================================================

class ExecutionPlanner:
    """
    第一版目标：
    1. 接 Arbiter 的通过结果
    2. 生成统一的执行步骤
    3. 支持 dry-run
    4. 后续可接 dispatcher 真执行
    """

    def build_plan(
        self,
        interpretation: InterpretationResult,
        decision: ArbiterDecision,
        runtime_context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        runtime_context = runtime_context or {}
        plan = ExecutionPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            summary="",
            steps=[],
            executable=False,
            blocked_reasons=[],
        )

        if decision.overall_verdict == "reject":
            plan.blocked_reasons.extend(decision.reasons or ["裁决结果为 reject"])
            plan.summary = "裁决拒绝，未生成执行计划。"
            return plan

        if decision.review_items and not decision.approved_items:
            plan.blocked_reasons.extend(decision.reasons or ["存在待复核建议"])
            plan.summary = "仅存在待复核建议，生成人工审阅计划。"
            plan.steps = self._build_review_steps(decision.review_items)
            plan.executable = False
            return plan

        steps: List[PlanStep] = []

        approved_steps = self._convert_items_to_steps(decision.approved_items)
        steps.extend(approved_steps)

        if decision.review_items:
            steps.extend(self._build_review_steps(decision.review_items))
            plan.blocked_reasons.append("部分建议需要人工确认，已附加 review 步骤")

        plan.steps = steps
        plan.executable = len(approved_steps) > 0
        plan.summary = self._build_summary(plan)
        return plan

    # --------------------------------------------------------
    # 执行
    # --------------------------------------------------------

    def execute(
        self,
        plan: ExecutionPlan,
        dispatcher: Optional[Any] = None,
        *,
        dry_run: bool = True,
        allow_shell: bool = False,
        dispatch_context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        dispatch_context = dispatch_context or {}
        result = ExecutionResult(plan_id=plan.plan_id, mode="dry_run" if dry_run else "execute")

        if not plan.steps:
            result.step_results.append(
                {
                    "status": "skipped",
                    "reason": "空计划，无步骤可执行",
                }
            )
            result.success = False
            return result

        all_ok = True

        for step in plan.steps:
            if dry_run:
                result.step_results.append(
                    {
                        "step_id": step.step_id,
                        "title": step.title,
                        "kind": step.kind,
                        "status": "dry_run",
                        "note": step.dry_run_note or "dry-run 模式未真实执行",
                    }
                )
                continue

            if step.kind == "manual":
                result.step_results.append(
                    {
                        "step_id": step.step_id,
                        "title": step.title,
                        "kind": step.kind,
                        "status": "manual_required",
                        "instruction": step.manual_instruction,
                    }
                )
                continue

            if step.kind == "action":
                ok, payload = self._execute_action_step(step, dispatcher, dispatch_context)
                result.step_results.append(payload)
                all_ok = all_ok and ok
                continue

            if step.kind == "shell":
                ok, payload = self._execute_shell_step(step, allow_shell=allow_shell)
                result.step_results.append(payload)
                all_ok = all_ok and ok
                continue

            result.step_results.append(
                {
                    "step_id": step.step_id,
                    "title": step.title,
                    "kind": step.kind,
                    "status": "skipped",
                    "reason": f"未知步骤类型: {step.kind}",
                }
            )
            all_ok = False

        result.success = all_ok
        return result

    # --------------------------------------------------------
    # 步骤构建
    # --------------------------------------------------------

    def _convert_items_to_steps(self, items: List[SuggestionItem]) -> List[PlanStep]:
        steps: List[PlanStep] = []
        prev_step_id: Optional[str] = None

        for idx, item in enumerate(items, start=1):
            step_id = f"step-{idx:02d}"
            depends_on = [prev_step_id] if prev_step_id else []

            if item.kind == "action":
                step = PlanStep(
                    step_id=step_id,
                    title=f"执行动作: {item.action_name or item.raw_text}",
                    kind="action",
                    action_name=item.action_name,
                    params=item.params,
                    depends_on=depends_on,
                    dry_run_note=f"将调用 dispatcher action: {item.action_name}",
                )
            elif item.kind == "shell":
                step = PlanStep(
                    step_id=step_id,
                    title="执行命令行建议",
                    kind="shell",
                    command=item.command or item.raw_text,
                    params=item.params,
                    depends_on=depends_on,
                    dry_run_note=f"将执行 shell: {item.command or item.raw_text}",
                )
            else:
                step = PlanStep(
                    step_id=step_id,
                    title="人工处理建议",
                    kind="manual",
                    manual_instruction=item.raw_text,
                    depends_on=depends_on,
                    dry_run_note="该步骤仅供人工执行",
                )

            steps.append(step)
            prev_step_id = step_id

        return steps

    def _build_review_steps(self, items: List[SuggestionItem]) -> List[PlanStep]:
        out: List[PlanStep] = []
        for idx, item in enumerate(items, start=1):
            out.append(
                PlanStep(
                    step_id=f"review-{idx:02d}",
                    title="人工复核建议",
                    kind="manual",
                    manual_instruction=item.raw_text,
                    dry_run_note="该建议需人工确认后再执行",
                )
            )
        return out

    def _build_summary(self, plan: ExecutionPlan) -> str:
        if not plan.steps:
            return "无可执行步骤。"
        return " -> ".join([s.title for s in plan.steps])

    # --------------------------------------------------------
    # 真执行桥接
    # --------------------------------------------------------

    def _extract_context_payload(
        self,
        step: PlanStep,
        dispatch_context: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        返回:
        - context_value: 给 action 的 context 参数
        - local_params: 真实业务 kwargs

        关键修复点：
        1. 把 runtime_context 平铺到 action kwargs
        2. 保留 context 这个专用入口
        3. step.params 优先级高于 dispatch_context
        """
        raw_context = dict(dispatch_context or {})
        step_params = dict(step.params or {})

        # context 专门留给 action 的 context 参数
        context_value = dict(raw_context)
        if "context" in step_params and isinstance(step_params["context"], dict):
            context_value.update(step_params["context"])

        # 业务参数：dispatch_context 先铺底，step.params 再覆盖
        local_params: Dict[str, Any] = {}
        for k, v in raw_context.items():
            if k == "context":
                continue
            local_params[k] = v

        for k, v in step_params.items():
            if k == "context":
                continue
            local_params[k] = v

        return context_value, local_params

    def _normalize_output_status(
        self,
        output: Any,
    ) -> tuple[bool, Optional[str], str]:
        """
        统一动作语义：
        - dict 且 ok=False -> failed
        - 其他默认 ok
        """
        if isinstance(output, dict):
            if output.get("ok") is False:
                reason = (
                    output.get("reason")
                    or output.get("error")
                    or "action_reported_failure"
                )
                return False, str(reason), "failed"
            return True, None, "ok"
        return True, None, "ok"

    def _filter_kwargs_for_callable(
        self,
        fn: Any,
        kwargs: Dict[str, Any],
    ) -> tuple[Dict[str, Any], bool]:
        """
        按签名过滤 kwargs。
        返回:
        - filtered kwargs
        - 是否支持 **kwargs
        """
        try:
            sig = inspect.signature(fn)
        except Exception:
            return dict(kwargs), True

        params = sig.parameters
        accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_var_kw:
            return dict(kwargs), True

        accepted = {}
        for name, value in kwargs.items():
            if name in params:
                accepted[name] = value
        return accepted, False

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
        tried: List[str] = []

        def _resolve_call_action_target(obj: Any) -> Optional[Any]:
            if obj is None:
                return None
            caller = getattr(obj, "call_action", None)
            if callable(caller):
                return obj
            ctx = getattr(obj, "context", None)
            caller = getattr(ctx, "call_action", None)
            if callable(caller):
                return ctx
            return None

        try:
            _context_value, local_params = self._extract_context_payload(step, dispatch_context)

            # ----------------------------------------------------
            # 第一优先级：统一入口 context.call_action(...)
            # ----------------------------------------------------
            call_action_target = _resolve_call_action_target(dispatcher)
            if call_action_target is not None:
                tried.append("call_action")
                output = call_action_target.call_action(action_name, params=local_params)
                ok, reason, final_status = self._normalize_output_status(output)

                payload = {
                    "step_id": step.step_id,
                    "title": step.title,
                    "kind": step.kind,
                    "status": final_status,
                    "action_name": action_name,
                    "output": output,
                    "bridge_method": "call_action(action_name, params=...)",
                }
                if reason:
                    payload["reason"] = reason
                return ok, payload

            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "action_name": action_name,
                "reason": "缺少标准 context.call_action 执行接口",
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

    def _execute_shell_step(self, step: PlanStep, allow_shell: bool) -> tuple[bool, Dict[str, Any]]:
        if not allow_shell:
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "blocked",
                "reason": "当前执行器未放行 shell",
            }

        try:
            proc = subprocess.run(
                step.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            ok = proc.returncode == 0
            return ok, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "ok" if ok else "failed",
                "command": step.command,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as exc:
            return False, {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "status": "failed",
                "command": step.command,
                "reason": str(exc),
            }
