# core/aicore/intent_action_generator/action_synthesizer.py

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, Callable
import time

from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER

logger = get_logger("ActionSynthesizer")


@dataclass
class ActionPlan:
    """
    企业可演进版“执行计划”结构。
    AICore/GUI/HTTP/自动化统一只处理 plan，不直接调用函数。
    """
    type: str = "action"
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    source: str = "intent"           # router|alias|intent|llm
    confidence: float = 0.85
    need_confirm: bool = False
    risk: str = "low"                # low|medium|high

    intent: Optional[str] = None
    reason: str = ""
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ActionSynthesizer:
    """
    Planner：intent_obj -> ActionPlan
    """

    HIGH_RISK_ACTIONS = {
        "shutdown", "reboot", "logout", "suspend",
        "system.shutdown", "system.reboot", "system.logout", "system.suspend",
        "close_app", "system.kill", "system.pkill",
    }

    DEFAULT_INTENT_TO_ACTION = {
        "shutdown": "shutdown",
        "reboot": "reboot",
        "logout": "logout",
        "suspend": "suspend",
        "lock_screen": "lock_screen",
        "turn_off_display": "turn_off_display",

        "play_music": "play_music",
        "pause_music": "pause_music",
        "stop_music": "stop_music",
        "next_song": "next_song",
        "previous_song": "previous_song",
        "loop_one_on": "loop_one_on",
        "loop_one_off": "loop_one_off",
        "play_video_file": "play_video_file",

        "screenshot": "screenshot",
        "open_browser": "open_browser",
        "open_url": "open_url",
        "show_time": "show_time",
        "show_date": "show_date",
        "check_network": "check_network",
        "weather_query": "weather_query",
        "set_reminder": "set_reminder",
        "close_app": "close_app",

        "remember": "memory.add",
        "search_memory": "memory.search",
        "search": "memory.search",
    }

    def __init__(self, registry: Any = None):
        # registry 推荐为 IntentRegistry（只维护 intent->action_name）
        self.registry = registry

    def synthesize(self, intent_obj: Dict[str, Any]) -> Optional[ActionPlan]:
        try:
            if not isinstance(intent_obj, dict):
                return None

            intent = (intent_obj.get("intent") or "").strip()
            params = intent_obj.get("params") or {}
            if not isinstance(params, dict):
                params = {}

            # 1) recognizer 显式给 action_name 最可信
            action = (intent_obj.get("action_name") or "").strip()

            # 2) registry: intent -> action_name（企业主路径）
            if not action and intent:
                action = self._resolve_action_from_registry(intent) or ""

            # 3) fallback mapping
            if not action and intent:
                action = self.DEFAULT_INTENT_TO_ACTION.get(intent, "")

            if not action:
                logger.warning(f"❓ synthesize: 无法编排 intent -> action: intent={intent}")
                return None

            # 4) 风险治理：优先读 dispatcher meta.extra，其次内置名单
            risk, need_confirm = self._govern(action)

            exists = bool(ACTION_MANAGER.get_action(action))
            confidence = 0.90 if exists else 0.72

            plan = ActionPlan(
                action=action,
                params=params,
                source="intent",
                confidence=confidence,
                need_confirm=need_confirm,
                risk=risk,
                intent=intent,
                reason="dispatcher_exists" if exists else "dispatcher_missing_but_planned",
            )
            logger.info(f"🧭 ActionPlan: intent={intent} -> action={action}, risk={risk}, confirm={need_confirm}, params={params}")
            return plan

        except Exception as e:
            logger.error(f"❌ synthesize 异常: {e}")
            return None

    def _resolve_action_from_registry(self, intent: str) -> Optional[str]:
        if not intent or not self.registry:
            return None

        # 企业推荐接口：get_action/resolve/resolve_action
        for attr in ("get_action", "resolve", "resolve_action"):
            fn = getattr(self.registry, attr, None)
            if callable(fn):
                try:
                    v = fn(intent)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                except Exception:
                    pass

        # 兼容极老实现：registry.get(intent) 若返回 str 才当 action
        get_fn = getattr(self.registry, "get", None)
        if callable(get_fn):
            try:
                v = get_fn(intent)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            except Exception:
                pass

        return None

    def _govern(self, action: str) -> (str, bool):
        # 1) dispatcher meta.extra（企业治理主路径）
        try:
            meta = ACTION_MANAGER.get_action(action)
            if meta and getattr(meta, "extra", None):
                extra = meta.extra or {}
                risk = extra.get("risk")
                need_confirm = extra.get("need_confirm")
                if isinstance(risk, str) and risk.strip():
                    if isinstance(need_confirm, bool):
                        return risk.strip(), need_confirm
                    return risk.strip(), (risk.strip() in ("medium", "high"))
        except Exception:
            pass

        # 2) 内置高风险名单兜底
        if action in self.HIGH_RISK_ACTIONS:
            return "high", True

        return "low", False

    # 过渡期兼容
    def synthesize_callable(self, intent_obj: Dict[str, Any]) -> Optional[Callable]:
        plan = self.synthesize(intent_obj)
        if not plan:
            return None

        def _runner(ctx, query: str = "", **kwargs):
            merged = {}
            merged.update(plan.params or {})
            merged.update(kwargs or {})
            return ACTION_MANAGER.execute(plan.action, query=query, params=merged)

        return _runner