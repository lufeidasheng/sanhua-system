#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
core.aicore.aicore

稳定契约：
- 给 modules/aicore_module/module.py 提供稳定入口：get_aicore_instance()
- 避免 ImportError: cannot import name 'get_aicore_instance'
- 内部返回 ExtensibleAICore 单例（企业可扩展版）

新增能力：
- 在单例初始化后挂载 MemoryManager / PromptMemoryBridge
- 在单例初始化后挂载 SuggestionInterpreter / DecisionArbiter / ExecutionPlanner
- 在单例初始化后挂载 RollbackManager / ChangeValidator / ApplyPatchEngine
- 在单例初始化后挂载 SelfEvolutionOrchestrator

对外暴露统一记忆辅助方法：
    - build_memory_prompt(...)
    - build_memory_payload(...)
    - record_chat_memory(...)
    - record_action_memory(...)
    - memory_snapshot()
    - memory_health()
    - add_long_term_memory(...)

对外暴露统一建议闭环方法：
    - process_suggestion_chain(...)
    - debug_suggestion_chain(...)

对外暴露统一自演化闭环方法：
    - create_rollback_snapshot(...)
    - rollback_snapshot(...)
    - validate_change_set(...)
    - safe_apply_change_set(...)

对外暴露统一编排器入口：
    - evolve_file_replace(...)
    - evolve_file_append(...)

说明：
- 真正把“记忆增强 prompt”送入模型的动作，
  应在 ExtensibleAICore 的实际模型调用前接入：
      aicore.build_memory_prompt(user_input, session_context=...)

- 真正把“模型建议文本”接到系统闭环，
  当前建议先通过：
      aicore.process_suggestion_chain(..., dry_run=True)
  做 dry-run 验证，稳定后再逐步放行低风险 action。

- 真正把“正式补丁落盘 + 验证 + 回滚”接到系统闭环，
  当前建议先通过：
      aicore.safe_apply_change_set(...)
  在严格校验条件下使用。
"""

from __future__ import annotations

import atexit
import logging
import threading
import types
from pathlib import Path
from typing import Any, Optional

_AICORE_SINGLETON = None
_LOCK = threading.RLock()


def _get_logger() -> logging.Logger:
    return logging.getLogger("core.aicore.aicore")


def _safe_log(level: str, msg: str, *args: Any) -> None:
    logger = _get_logger()
    try:
        getattr(logger, level, logger.info)(msg, *args)
    except Exception:
        pass


def _project_root_from_here() -> str:
    """
    从当前文件位置推导项目根目录：
    core/aicore/aicore.py -> 项目根目录
    """
    try:
        return str(Path(__file__).resolve().parents[2])
    except Exception:
        return str(Path.cwd().resolve())


def _safe_to_dict(obj: Any) -> dict:
    """
    兼容第三方/项目内返回对象：
    - 已经是 dict
    - 拥有 to_dict()
    - 其他类型则尽量包成 dict
    """
    try:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            return obj.to_dict()
    except Exception:
        pass
    return {"ok": False, "reason": f"unsupported_result_type:{type(obj)}", "raw": str(obj)}


def _wire_memory_support(aicore: Any) -> Any:
    """
    给 ExtensibleAICore 单例挂载正式记忆能力。
    这里只做“挂能力”和“暴露统一接口”，
    不直接替换 chat 主逻辑，避免影响现有 AICore 行为。
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_memory_support_wired", False):
        return aicore

    try:
        from core.memory_engine.memory_manager import MemoryManager
        from core.prompt_engine.prompt_memory_bridge import PromptMemoryBridge
    except Exception as e:
        _safe_log("warning", "挂载记忆能力失败，导入组件异常: %s", e)
        return aicore

    try:
        if not hasattr(aicore, "memory_manager") or getattr(aicore, "memory_manager", None) is None:
            aicore.memory_manager = MemoryManager()
            _safe_log("info", "已挂载 MemoryManager 到 AICore 单例")
    except Exception as e:
        _safe_log("warning", "初始化 MemoryManager 失败: %s", e)

    try:
        if not hasattr(aicore, "prompt_memory_bridge") or getattr(aicore, "prompt_memory_bridge", None) is None:
            aicore.prompt_memory_bridge = PromptMemoryBridge(
                memory_manager=getattr(aicore, "memory_manager", None)
            )
            _safe_log("info", "已挂载 PromptMemoryBridge 到 AICore 单例")
    except Exception as e:
        _safe_log("warning", "初始化 PromptMemoryBridge 失败: %s", e)

    if not hasattr(aicore, "system_persona"):
        try:
            aicore.system_persona = ""
        except Exception:
            pass

    def _ensure_default_session(self) -> None:
        try:
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return

            active = mm.get_active_session()
            if not active.get("session_id"):
                mm.set_active_session(
                    session_id="aicore_default_session",
                    context_summary="AICore 默认会话",
                )
        except Exception as e:
            _safe_log("warning", "确保默认 session 失败: %s", e)

    def build_memory_prompt(
        self,
        user_input: str,
        session_context: Any = None,
        system_persona: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        bridge = getattr(self, "prompt_memory_bridge", None)
        if bridge is None:
            return user_input

        persona_text = (
            system_persona
            if system_persona is not None
            else getattr(self, "system_persona", "") or ""
        )

        try:
            return bridge.build_prompt(
                user_input=user_input,
                system_persona=persona_text,
                session_context=session_context,
                **kwargs,
            )
        except Exception as e:
            _safe_log("warning", "构建记忆增强 prompt 失败，回退原输入: %s", e)
            return user_input

    def build_memory_payload(
        self,
        user_input: str,
        session_context: Any = None,
        system_persona: Optional[str] = None,
        **kwargs: Any,
    ) -> dict:
        bridge = getattr(self, "prompt_memory_bridge", None)
        if bridge is None:
            return {
                "user_input": user_input,
                "final_prompt": user_input,
                "memory_context_text": "",
                "selected_long_term_memories": [],
            }

        persona_text = (
            system_persona
            if system_persona is not None
            else getattr(self, "system_persona", "") or ""
        )

        try:
            return bridge.build_prompt_payload(
                user_input=user_input,
                system_persona=persona_text,
                session_context=session_context,
                **kwargs,
            )
        except Exception as e:
            _safe_log("warning", "构建记忆 payload 失败: %s", e)
            return {
                "user_input": user_input,
                "final_prompt": user_input,
                "memory_context_text": "",
                "selected_long_term_memories": [],
                "error": str(e),
            }

    def record_chat_memory(self, role: str, content: str) -> None:
        try:
            self._ensure_default_session()
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return
            mm.append_recent_message(role=role, content=content)
        except Exception as e:
            _safe_log("warning", "记录会话记忆失败: %s", e)

    def record_action_memory(
        self,
        action_name: str,
        status: str = "success",
        result_summary: str = "",
    ) -> None:
        try:
            self._ensure_default_session()
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return
            mm.append_recent_action(
                action_name=action_name,
                status=status,
                result_summary=result_summary,
            )
        except Exception as e:
            _safe_log("warning", "记录动作记忆失败: %s", e)

    def memory_snapshot(self) -> dict:
        try:
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return {}
            return mm.snapshot()
        except Exception as e:
            _safe_log("warning", "获取 memory snapshot 失败: %s", e)
            return {"error": str(e)}

    def memory_health(self) -> dict:
        try:
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return {"ok": False, "reason": "memory_manager_not_ready"}
            return mm.health_check()
        except Exception as e:
            _safe_log("warning", "获取 memory health 失败: %s", e)
            return {"ok": False, "error": str(e)}

    def add_long_term_memory(
        self,
        content: Any,
        memory_type: str = "fact",
        importance: float = 0.5,
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        try:
            mm = getattr(self, "memory_manager", None)
            if mm is None:
                return None
            return mm.add_long_term_memory(
                content=content,
                memory_type=memory_type,
                importance=importance,
                tags=tags,
                metadata=metadata,
            )
        except Exception as e:
            _safe_log("warning", "写入长期记忆失败: %s", e)
            return None

    method_map = {
        "_ensure_default_session": _ensure_default_session,
        "build_memory_prompt": build_memory_prompt,
        "build_memory_payload": build_memory_payload,
        "record_chat_memory": record_chat_memory,
        "record_action_memory": record_action_memory,
        "memory_snapshot": memory_snapshot,
        "memory_health": memory_health,
        "add_long_term_memory": add_long_term_memory,
    }

    for method_name, func in method_map.items():
        if not hasattr(aicore, method_name):
            try:
                setattr(aicore, method_name, types.MethodType(func, aicore))
            except Exception as e:
                _safe_log("warning", "绑定方法失败 %s: %s", method_name, e)

    try:
        if hasattr(aicore, "_ensure_default_session"):
            aicore._ensure_default_session()
    except Exception as e:
        _safe_log("warning", "初始化默认 session 失败: %s", e)

    try:
        aicore._memory_support_wired = True
    except Exception:
        pass

    return aicore


def _wire_decision_support(aicore: Any) -> Any:
    """
    给 ExtensibleAICore 单例挂载“建议解释 -> 风险裁决 -> 执行计划”能力。
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_decision_support_wired", False):
        return aicore

    try:
        from core.core2_0.sanhuatongyu.suggestion_interpreter import SuggestionInterpreter
        from core.core2_0.sanhuatongyu.decision_arbiter import DecisionArbiter, ArbiterPolicy
        from core.core2_0.sanhuatongyu.execution_planner import ExecutionPlanner
    except Exception as e:
        _safe_log("warning", "挂载决策链失败，导入组件异常: %s", e)
        return aicore

    def _resolve_dispatcher(self) -> Any:
        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            try:
                obj = getattr(self, name, None)
                if obj is not None:
                    return obj
            except Exception:
                continue

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
            if ACTION_MANAGER is not None:
                return ACTION_MANAGER
        except Exception:
            pass

        try:
            from core.core2_0.sanhuatongyu.action_dispatcher import get_global_dispatcher
            dispatcher = get_global_dispatcher()
            if dispatcher is not None:
                return dispatcher
        except Exception:
            pass

        return None

    def _init_decision_chain(self) -> None:
        try:
            self.suggestion_interpreter = SuggestionInterpreter()
            self.decision_arbiter = DecisionArbiter(
                ArbiterPolicy(
                    allow_shell=False,
                    allow_file_write=False,
                    allow_network_change=False,
                    min_confidence=0.45,
                    force_review_on_high_risk=True,
                    allowed_action_prefixes=[
                        "sysmon.",
                        "memory.",
                        "ai.ask",
                        "system.",
                        "code_reader.",
                        "code_reviewer.",
                        "code_executor.syntax_",
                        "code_inserter.preview_",
                    ],
                )
            )
            self.execution_planner = ExecutionPlanner()
            self._decision_chain_enabled = True
            _safe_log("info", "已挂载 SuggestionInterpreter / DecisionArbiter / ExecutionPlanner")
        except Exception as e:
            self._decision_chain_enabled = False
            _safe_log("warning", "初始化决策链失败: %s", e)

    def process_suggestion_chain(
        self,
        suggestion_text: str,
        *,
        user_query: str = "",
        runtime_context: Optional[dict] = None,
        dry_run: bool = True,
    ) -> dict:
        runtime_context = runtime_context or {}

        if not getattr(self, "_decision_chain_enabled", False):
            raise RuntimeError("决策链尚未初始化，请先调用 _init_decision_chain()")

        interpretation = self.suggestion_interpreter.interpret(
            suggestion_text,
            source="llm",
            context={
                "user_query": user_query,
                **runtime_context,
            },
        )

        decision = self.decision_arbiter.arbitrate(
            interpretation,
            runtime_context=runtime_context,
        )

        plan = self.execution_planner.build_plan(
            interpretation,
            decision,
            runtime_context=runtime_context,
        )

        execution = self.execution_planner.execute(
            plan,
            dispatcher=self._resolve_dispatcher(),
            dry_run=dry_run,
            allow_shell=runtime_context.get("allow_shell", False),
            dispatch_context=runtime_context,
        )

        return {
            "interpretation": interpretation.to_dict(),
            "decision": decision.to_dict(),
            "plan": plan.to_dict(),
            "execution": execution.to_dict(),
        }

    def debug_suggestion_chain(
        self,
        suggestion_text: str,
        *,
        user_query: str = "",
        runtime_context: Optional[dict] = None,
    ) -> dict:
        return self.process_suggestion_chain(
            suggestion_text=suggestion_text,
            user_query=user_query,
            runtime_context=runtime_context or {},
            dry_run=True,
        )

    method_map = {
        "_resolve_dispatcher": _resolve_dispatcher,
        "_init_decision_chain": _init_decision_chain,
        "process_suggestion_chain": process_suggestion_chain,
        "debug_suggestion_chain": debug_suggestion_chain,
    }

    for method_name, func in method_map.items():
        if not hasattr(aicore, method_name):
            try:
                setattr(aicore, method_name, types.MethodType(func, aicore))
            except Exception as e:
                _safe_log("warning", "绑定决策链方法失败 %s: %s", method_name, e)

    try:
        if hasattr(aicore, "_init_decision_chain"):
            aicore._init_decision_chain()
    except Exception as e:
        _safe_log("warning", "自动初始化决策链失败: %s", e)

    try:
        aicore._decision_support_wired = True
    except Exception:
        pass

    return aicore


def _wire_action_bootstrap_support(aicore: Any) -> Any:
    """
    给 AICore 单例挂载“最小动作注册引导”能力。
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_action_bootstrap_support_wired", False):
        return aicore

    def _normalize_actions(raw):
        if raw is None:
            return []
        if isinstance(raw, dict):
            return list(raw.keys())
        if isinstance(raw, (list, tuple, set)):
            out = []
            for item in raw:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("action")
                    if name:
                        out.append(str(name))
                else:
                    out.append(str(item))
            return out
        return [str(raw)]

    def _bootstrap_action_registry(self, force: bool = False) -> dict:
        import importlib
        import inspect
        import os
        import platform
        import shutil
        import time

        dispatcher = self._resolve_dispatcher() if hasattr(self, "_resolve_dispatcher") else None
        if dispatcher is None:
            return {
                "ok": False,
                "reason": "dispatcher_not_ready",
                "count_before": 0,
                "count_after": 0,
                "details": [],
            }

        def _list_count() -> int:
            try:
                return len(set(_normalize_actions(dispatcher.list_actions())))
            except Exception:
                return 0

        count_before = _list_count()
        details = []

        current_actions = set()
        try:
            current_actions = set(_normalize_actions(dispatcher.list_actions()))
        except Exception:
            current_actions = set()

        has_ai = any(str(x).startswith("ai.") for x in current_actions)
        has_sysmon = any(str(x).startswith("sysmon.") for x in current_actions)
        has_system = any(str(x).startswith("system.") for x in current_actions)
        has_memory = any(str(x).startswith("memory.") for x in current_actions)
        has_code_reader = any(str(x).startswith("code_reader.") for x in current_actions)
        has_code_reviewer = any(str(x).startswith("code_reviewer.") for x in current_actions)
        has_code_executor = any(str(x).startswith("code_executor.") for x in current_actions)

        core_bootstrap_ready = (
            has_ai
            and (has_sysmon or has_system)
            and has_memory
            and (has_code_reader or has_code_reviewer or has_code_executor)
        )

        if count_before > 0 and core_bootstrap_ready and not force:
            return {
                "ok": True,
                "reason": "dispatcher_already_has_core_actions",
                "count_before": count_before,
                "count_after": count_before,
                "details": [],
            }

        try:
            if hasattr(dispatcher, "set_context"):
                dispatcher.set_context({"source": "aicore.bootstrap_action_registry"})
        except Exception:
            pass

        try:
            importlib.import_module("core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp")
            details.append({"step": "import_ai_actions", "ok": True})
        except Exception as e:
            details.append({"step": "import_ai_actions", "ok": False, "error": str(e)})

        for mod_name in ("entry.gui_main", "entry.gui_entry.gui_main"):
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "register_actions") and callable(getattr(mod, "register_actions")):
                    mod.register_actions(dispatcher)
                    details.append({"step": f"{mod_name}.register_actions", "ok": True})
                else:
                    details.append({"step": f"{mod_name}.register_actions", "ok": False, "error": "not_found"})
            except Exception as e:
                details.append({"step": f"{mod_name}.register_actions", "ok": False, "error": str(e)})

        safe_modules = (
            "modules.system_monitor.module",
            "modules.system_control.module",
            "modules.code_reader.module",
            "modules.code_executor.module",
            "modules.code_inserter.module",
            "modules.code_reviewer.module",
            "modules.logbook.module",
        )

        for mod_name in safe_modules:
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:
                details.append({"step": mod_name, "ok": False, "error": f"import failed: {e}"})
                continue

            if not hasattr(mod, "register_actions") or not callable(getattr(mod, "register_actions")):
                details.append({"step": mod_name, "ok": False, "error": "register_actions not found"})
                continue

            fn = getattr(mod, "register_actions")
            try:
                sig = inspect.signature(fn)
                params = [
                    p for p in sig.parameters.values()
                    if p.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                ]
                if len(params) == 0:
                    fn()
                    details.append({"step": mod_name, "ok": True, "mode": "register_actions()"})
                else:
                    fn(dispatcher)
                    details.append({"step": mod_name, "ok": True, "mode": "register_actions(dispatcher)"})
            except Exception as e:
                details.append({"step": mod_name, "ok": False, "error": str(e)})

        try:
            from utils.alias_loader import load_aliases_from_yaml

            project_root = Path(_project_root_from_here())
            alias_path = project_root / "config" / "aliases.yaml"
            if alias_path.exists():
                n = load_aliases_from_yaml(str(alias_path), dispatcher)
                details.append({"step": "aliases", "ok": True, "count": int(n or 0)})
            else:
                details.append({"step": "aliases", "ok": False, "error": "config/aliases.yaml not found"})
        except Exception as e:
            details.append({"step": "aliases", "ok": False, "error": str(e)})

        try:
            existing = None
            if hasattr(dispatcher, "get_action"):
                existing = dispatcher.get_action("sysmon.status")

            if existing is None and hasattr(dispatcher, "register_action"):
                try:
                    import psutil  # type: ignore
                except Exception:
                    psutil = None

                def _fallback_sysmon_status(context=None, **kwargs):
                    data = {
                        "ok": True,
                        "source": "aicore_fallback",
                        "timestamp": int(time.time()),
                        "platform": platform.platform(),
                        "python": platform.python_version(),
                        "cwd": os.getcwd(),
                    }

                    try:
                        if psutil is not None:
                            vm = psutil.virtual_memory()
                            du = psutil.disk_usage("/")
                            cpu = psutil.cpu_percent(interval=0.1)
                            data.update({
                                "cpu_percent": cpu,
                                "memory_total": int(vm.total),
                                "memory_used": int(vm.used),
                                "memory_available": int(vm.available),
                                "memory_percent": float(vm.percent),
                                "disk_total": int(du.total),
                                "disk_used": int(du.used),
                                "disk_free": int(du.free),
                            })
                        else:
                            du = shutil.disk_usage("/")
                            data.update({
                                "cpu_percent": None,
                                "memory_total": None,
                                "memory_used": None,
                                "memory_available": None,
                                "memory_percent": None,
                                "disk_total": int(du.total),
                                "disk_used": int(du.used),
                                "disk_free": int(du.free),
                            })
                    except Exception as inner_e:
                        data["metrics_error"] = str(inner_e)

                    if context is not None:
                        data["context"] = context
                    if kwargs:
                        data["kwargs"] = kwargs

                    return data

                dispatcher.register_action("sysmon.status", _fallback_sysmon_status)
                details.append({
                    "step": "fallback.sysmon.status",
                    "ok": True,
                    "mode": "direct_register",
                })
            else:
                details.append({
                    "step": "fallback.sysmon.status",
                    "ok": True,
                    "mode": "already_exists",
                })
        except Exception as e:
            details.append({
                "step": "fallback.sysmon.status",
                "ok": False,
                "error": str(e),
            })


        # 4.5) memory actions
        try:
            from tools.memory_actions_official import register_actions as register_memory_actions
            mem_res = register_memory_actions(dispatcher=dispatcher, aicore=self)
            details.append({
                "step": "memory_actions",
                "ok": bool(mem_res.get("ok")),
                "count_registered": int(mem_res.get("count_registered", 0)),
                "count_failed": int(mem_res.get("count_failed", 0)),
                "registered": list(mem_res.get("registered", [])),
                "failed": list(mem_res.get("failed", [])),
            })
        except Exception as e:
            details.append({
                "step": "memory_actions",
                "ok": False,
                "error": str(e),
            })

        count_after = _list_count()

        return {
            "ok": count_after > 0,
            "reason": "bootstrapped" if count_after > 0 else "still_empty",
            "count_before": count_before,
            "count_after": count_after,
            "details": details,
        }

    if not hasattr(aicore, "_bootstrap_action_registry"):
        try:
            setattr(aicore, "_bootstrap_action_registry", types.MethodType(_bootstrap_action_registry, aicore))
        except Exception as e:
            _safe_log("warning", "绑定 _bootstrap_action_registry 失败: %s", e)

    try:
        aicore._action_bootstrap_support_wired = True
    except Exception:
        pass

    return aicore


def _wire_self_evolution_support(aicore: Any) -> Any:
    """
    给 AICore 单例挂上正式写盘闭环：
    - rollback_manager
    - change_validator
    - apply_patch_engine
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_self_evolution_support_wired", False):
        return aicore

    try:
        from core.core2_0.sanhuatongyu.rollback_manager import RollbackManager
        from core.core2_0.sanhuatongyu.change_validator import ChangeValidator
        from core.core2_0.sanhuatongyu.apply_patch import ApplyPatchEngine
    except Exception as e:
        _safe_log("warning", "挂载自演化能力失败，导入组件异常: %s", e)
        return aicore

    root_dir = None
    try:
        root_dir = getattr(getattr(aicore, "config", None), "root_dir", None)
    except Exception:
        root_dir = None

    if not root_dir:
        root_dir = _project_root_from_here()

    try:
        if not hasattr(aicore, "rollback_manager") or getattr(aicore, "rollback_manager", None) is None:
            aicore.rollback_manager = RollbackManager(root=root_dir)
            _safe_log("info", "已挂载 RollbackManager 到 AICore 单例")
    except Exception as e:
        _safe_log("warning", "初始化 RollbackManager 失败: %s", e)

    try:
        if not hasattr(aicore, "change_validator") or getattr(aicore, "change_validator", None) is None:
            aicore.change_validator = ChangeValidator(root=root_dir)
            _safe_log("info", "已挂载 ChangeValidator 到 AICore 单例")
    except Exception as e:
        _safe_log("warning", "初始化 ChangeValidator 失败: %s", e)

    try:
        if not hasattr(aicore, "apply_patch_engine") or getattr(aicore, "apply_patch_engine", None) is None:
            aicore.apply_patch_engine = ApplyPatchEngine(
                root=root_dir,
                rollback_manager=getattr(aicore, "rollback_manager", None),
            )
            _safe_log("info", "已挂载 ApplyPatchEngine 到 AICore 单例")
    except Exception as e:
        _safe_log("warning", "初始化 ApplyPatchEngine 失败: %s", e)

    def _best_dispatcher(self):
        for name in ("dispatcher", "action_dispatcher", "ACTION_MANAGER", "action_manager"):
            try:
                obj = getattr(self, name, None)
                if obj is not None:
                    return obj
            except Exception:
                continue

        getter = getattr(self, "_resolve_dispatcher", None)
        if callable(getter):
            try:
                dispatcher = getter()
                if dispatcher is not None:
                    return dispatcher
            except Exception:
                pass

        return None

    def create_rollback_snapshot(
        self,
        paths: list,
        reason: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        try:
            rm = getattr(self, "rollback_manager", None)
            if rm is None:
                return {"ok": False, "reason": "rollback_manager_not_ready"}
            snap = rm.create_snapshot(paths, reason=reason, metadata=metadata)
            out = _safe_to_dict(snap)
            out.setdefault("ok", True)
            return out
        except Exception as e:
            _safe_log("warning", "创建快照失败: %s", e)
            return {"ok": False, "reason": str(e)}

    def rollback_snapshot(self, snapshot_id: str) -> dict:
        try:
            rm = getattr(self, "rollback_manager", None)
            if rm is None:
                return {"ok": False, "reason": "rollback_manager_not_ready"}
            return _safe_to_dict(rm.rollback(snapshot_id))
        except Exception as e:
            _safe_log("warning", "回滚失败: %s", e)
            return {"ok": False, "reason": str(e)}

    def validate_change_set(
        self,
        checks: list,
        dispatcher: Optional[Any] = None,
    ) -> dict:
        try:
            validator = getattr(self, "change_validator", None)
            if validator is None:
                return {"ok": False, "reason": "change_validator_not_ready"}
            report = validator.run_checks(checks, dispatcher=dispatcher or self._best_dispatcher())
            return _safe_to_dict(report)
        except Exception as e:
            _safe_log("warning", "验证变更失败: %s", e)
            return {"ok": False, "reason": str(e)}

    def safe_apply_change_set(
        self,
        operations: list,
        *,
        reason: str = "",
        metadata: Optional[dict] = None,
        dry_run: bool = False,
        validation_checks: Optional[list] = None,
    ) -> dict:
        try:
            engine = getattr(self, "apply_patch_engine", None)
            if engine is None:
                return {"ok": False, "reason": "apply_patch_engine_not_ready"}

            apply_result = _safe_to_dict(
                engine.apply_changes(
                    operations,
                    reason=reason or "safe_apply_change_set",
                    metadata=metadata,
                    dry_run=dry_run,
                )
            )

            out = {
                "ok": bool(apply_result.get("ok")),
                "apply": apply_result,
                "validation": None,
                "rollback": None,
            }

            if dry_run or not apply_result.get("ok"):
                out["ok"] = bool(apply_result.get("ok"))
                return out

            if validation_checks:
                validation = self.validate_change_set(
                    validation_checks,
                    dispatcher=self._best_dispatcher(),
                )
                out["validation"] = validation

                if not validation.get("ok"):
                    snapshot_id = apply_result.get("snapshot_id")
                    if snapshot_id:
                        rollback = self.rollback_snapshot(snapshot_id)
                        out["rollback"] = rollback
                    out["ok"] = False
                    return out

            out["ok"] = True
            return out
        except Exception as e:
            _safe_log("warning", "安全应用变更失败: %s", e)
            return {
                "ok": False,
                "reason": str(e),
                "apply": None,
                "validation": None,
                "rollback": None,
            }

    method_map = {
        "_best_dispatcher": _best_dispatcher,
        "create_rollback_snapshot": create_rollback_snapshot,
        "rollback_snapshot": rollback_snapshot,
        "validate_change_set": validate_change_set,
        "safe_apply_change_set": safe_apply_change_set,
    }

    for method_name, func in method_map.items():
        if not hasattr(aicore, method_name):
            try:
                setattr(aicore, method_name, types.MethodType(func, aicore))
            except Exception as e:
                _safe_log("warning", "绑定自演化方法失败 %s: %s", method_name, e)

    try:
        aicore._self_evolution_support_wired = True
    except Exception:
        pass

    return aicore


def _wire_self_evolution_orchestrator_support(aicore: Any) -> Any:
    """
    给 AICore 单例挂载 SelfEvolutionOrchestrator。
    """
    if aicore is None:
        return aicore

    if getattr(aicore, "_self_evolution_orchestrator_wired", False):
        return aicore

    try:
        from core.core2_0.sanhuatongyu.self_evolution_orchestrator import SelfEvolutionOrchestrator
    except Exception as e:
        _safe_log("warning", "挂载 SelfEvolutionOrchestrator 失败，导入异常: %s", e)
        return aicore

    root_dir = None
    try:
        root_dir = getattr(getattr(aicore, "config", None), "root_dir", None)
    except Exception:
        root_dir = None

    if not root_dir:
        root_dir = _project_root_from_here()

    def _init_self_evolution_orchestrator(self) -> None:
        try:
            self.self_evolution_orchestrator = SelfEvolutionOrchestrator(
                aicore=self,
                root=root_dir,
            )
            self._self_evolution_orchestrator_enabled = True
            _safe_log("info", "已挂载 SelfEvolutionOrchestrator")
        except Exception as e:
            self._self_evolution_orchestrator_enabled = False
            _safe_log("warning", "初始化 SelfEvolutionOrchestrator 失败: %s", e)

    def evolve_file_replace(
        self,
        *,
        path: str,
        old: str,
        new: str,
        occurrence: int = 1,
        user_query: str = "",
        preview_only: bool = True,
        review_before: bool = True,
        review_after: bool = False,
        max_review_chars: int = 5000,
        extra_validation_checks: Optional[list] = None,
        import_module_after: Optional[str] = None,
    ) -> dict:
        if not getattr(self, "_self_evolution_orchestrator_enabled", False):
            raise RuntimeError("SelfEvolutionOrchestrator 尚未初始化")
        return self.self_evolution_orchestrator.run_text_replace_workflow(
            path=path,
            old=old,
            new=new,
            occurrence=occurrence,
            user_query=user_query,
            preview_only=preview_only,
            review_before=review_before,
            review_after=review_after,
            max_review_chars=max_review_chars,
            extra_validation_checks=extra_validation_checks,
            import_module_after=import_module_after,
        )

    def evolve_file_append(
        self,
        *,
        path: str,
        text: str,
        user_query: str = "",
        preview_only: bool = True,
        review_before: bool = True,
        review_after: bool = False,
        max_review_chars: int = 5000,
        extra_validation_checks: Optional[list] = None,
        import_module_after: Optional[str] = None,
    ) -> dict:
        if not getattr(self, "_self_evolution_orchestrator_enabled", False):
            raise RuntimeError("SelfEvolutionOrchestrator 尚未初始化")
        return self.self_evolution_orchestrator.run_text_append_workflow(
            path=path,
            text=text,
            user_query=user_query,
            preview_only=preview_only,
            review_before=review_before,
            review_after=review_after,
            max_review_chars=max_review_chars,
            extra_validation_checks=extra_validation_checks,
            import_module_after=import_module_after,
        )

    method_map = {
        "_init_self_evolution_orchestrator": _init_self_evolution_orchestrator,
        "evolve_file_replace": evolve_file_replace,
        "evolve_file_append": evolve_file_append,
    }

    for method_name, func in method_map.items():
        if not hasattr(aicore, method_name):
            try:
                setattr(aicore, method_name, types.MethodType(func, aicore))
            except Exception as e:
                _safe_log("warning", "绑定 SelfEvolutionOrchestrator 方法失败 %s: %s", method_name, e)

    try:
        if hasattr(aicore, "_init_self_evolution_orchestrator"):
            aicore._init_self_evolution_orchestrator()
    except Exception as e:
        _safe_log("warning", "自动初始化 SelfEvolutionOrchestrator 失败: %s", e)

    try:
        aicore._self_evolution_orchestrator_wired = True
    except Exception:
        pass

    return aicore


def get_aicore_instance(*args, **kwargs):
    """
    兼容旧调用：modules/aicore_module 会直接调这个函数拿全局 AICore
    """
    global _AICORE_SINGLETON
    with _LOCK:
        if _AICORE_SINGLETON is None:
            from core.aicore.config import AICoreConfig
            from core.aicore.extensible_aicore import ExtensibleAICore

            cfg = kwargs.pop("config", None) or AICoreConfig.from_env()
            _AICORE_SINGLETON = ExtensibleAICore(cfg)

            _AICORE_SINGLETON = _wire_memory_support(_AICORE_SINGLETON)
            _AICORE_SINGLETON = _wire_decision_support(_AICORE_SINGLETON)
            _AICORE_SINGLETON = _wire_action_bootstrap_support(_AICORE_SINGLETON)
            _AICORE_SINGLETON = _wire_self_evolution_support(_AICORE_SINGLETON)
            _AICORE_SINGLETON = _wire_self_evolution_orchestrator_support(_AICORE_SINGLETON)

            try:
                if hasattr(_AICORE_SINGLETON, "_bootstrap_action_registry"):
                    _AICORE_SINGLETON._bootstrap_action_registry(force=False)
            except Exception as e:
                _safe_log("warning", "启动期动作引导失败: %s", e)

            instance_ref = _AICORE_SINGLETON

            def _cleanup():
                try:
                    if instance_ref is not None and hasattr(instance_ref, "shutdown"):
                        instance_ref.shutdown()
                except Exception:
                    pass

            atexit.register(_cleanup)

        return _AICORE_SINGLETON


def get_aicore_class():
    from core.aicore.extensible_aicore import ExtensibleAICore
    return ExtensibleAICore


def reset_aicore_instance() -> None:
    """
    测试/重载辅助：清空单例。
    """
    global _AICORE_SINGLETON
    with _LOCK:
        try:
            if _AICORE_SINGLETON is not None and hasattr(_AICORE_SINGLETON, "shutdown"):
                _AICORE_SINGLETON.shutdown()
        except Exception:
            pass
        _AICORE_SINGLETON = None


try:
    from core.aicore.extensible_aicore import ExtensibleAICore as AICore  # noqa: F401
except Exception:
    AICore = None