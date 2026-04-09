# core/aicore/intent_action_generator/registry.py

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Any, Union, List

from core.core2_0.sanhuatongyu.logger import get_logger

logger = get_logger("IntentRegistry")


@dataclass
class IntentBinding:
    """
    企业级意图绑定元数据：
    - 支持绑定 callable
    - 支持绑定 dispatcher action_name（推荐）
    - 支持权限/风险/模块/版本/标签等治理字段
    """
    intent: str
    target: Union[Callable, str]                 # callable 或 action_name
    kind: str = "callable"                       # callable | action
    description: str = ""
    module: str = "aicore"
    permission: str = "user"                     # user|admin|system（你可扩展）
    risk: str = "low"                            # low|medium|high
    need_confirm: bool = False
    version: str = "1.0"
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        t = self.target
        target_repr = t if isinstance(t, str) else f"{getattr(t, '__module__', '')}.{getattr(t, '__name__', 'callable')}"
        return {
            "intent": self.intent,
            "kind": self.kind,
            "target": target_repr,
            "description": self.description,
            "module": self.module,
            "permission": self.permission,
            "risk": self.risk,
            "need_confirm": self.need_confirm,
            "version": self.version,
            "tags": list(self.tags),
            "extra": dict(self.extra),
        }


class IntentRegistry:
    """
    三花聚顶 · IntentRegistry（企业可演进版）

    企业关键契约：
    - get_action(intent) -> action_name(str|None)
    - resolve_action/resolve(intent) -> action_name(str|None)
    供 ActionSynthesizer(Planner) 编排使用。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._bindings: Dict[str, IntentBinding] = {}
        self._dispatcher = None  # 延迟绑定，避免循环依赖

    # -------------------------
    # 绑定 dispatcher
    # -------------------------
    def bind_dispatcher(self, dispatcher: Any) -> None:
        with self._lock:
            self._dispatcher = dispatcher
        logger.info(f"🔗 IntentRegistry 绑定 dispatcher: {type(dispatcher)}")

    # -------------------------
    # 注册
    # -------------------------
    def register(
        self,
        intent_name: str,
        func: Callable,
        *,
        description: str = "",
        module: str = "aicore",
        permission: str = "user",
        risk: str = "low",
        need_confirm: bool = False,
        version: str = "1.0",
        tags: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
        overwrite: bool = True,
    ) -> None:
        if not callable(func):
            raise ValueError(f"注册失败：{intent_name} 的绑定对象不是可调用函数")

        binding = IntentBinding(
            intent=intent_name,
            target=func,
            kind="callable",
            description=description,
            module=module,
            permission=permission,
            risk=risk,
            need_confirm=need_confirm,
            version=version,
            tags=tags or [],
            extra=extra or {},
        )

        with self._lock:
            if (intent_name in self._bindings) and not overwrite:
                raise KeyError(f"意图已存在且 overwrite=False: {intent_name}")
            self._bindings[intent_name] = binding

        logger.info(f"✅ 注册意图(callable): {intent_name} → {binding.to_dict()['target']}")

    def register_action(
        self,
        intent_name: str,
        action_name: str,
        *,
        description: str = "",
        module: str = "aicore",
        permission: str = "user",
        risk: str = "low",
        need_confirm: bool = False,
        version: str = "1.0",
        tags: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
        overwrite: bool = True,
    ) -> None:
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name 必须是非空字符串")

        binding = IntentBinding(
            intent=intent_name,
            target=action_name.strip(),
            kind="action",
            description=description,
            module=module,
            permission=permission,
            risk=risk,
            need_confirm=need_confirm,
            version=version,
            tags=tags or [],
            extra=extra or {},
        )

        with self._lock:
            if (intent_name in self._bindings) and not overwrite:
                raise KeyError(f"意图已存在且 overwrite=False: {intent_name}")
            self._bindings[intent_name] = binding

        logger.info(f"✅ 注册意图(action): {intent_name} → {action_name.strip()}")

    # -------------------------
    # 查询/获取
    # -------------------------
    def has_intent(self, intent_name: str) -> bool:
        with self._lock:
            return intent_name in self._bindings

    def get_binding(self, intent_name: str) -> Optional[IntentBinding]:
        with self._lock:
            return self._bindings.get(intent_name)

    # ===== 企业关键：Planner 读取 action_name =====
    def get_action(self, intent_name: str) -> Optional[str]:
        b = self.get_binding(intent_name)
        if not b:
            return None
        if b.kind == "action" and isinstance(b.target, str) and b.target.strip():
            return b.target.strip()
        return None

    def resolve_action(self, intent_name: str) -> Optional[str]:
        return self.get_action(intent_name)

    def resolve(self, intent_name: str) -> Optional[str]:
        return self.get_action(intent_name)

    # ===== 兼容旧代码：返回 callable =====
    def get(self, intent_name: str) -> Optional[Callable]:
        b = self.get_binding(intent_name)
        if not b:
            return None

        if b.kind == "callable":
            return b.target  # type: ignore[return-value]

        action_name = b.target  # type: ignore[assignment]

        def _wrapper(*args, **kwargs):
            disp = self._dispatcher
            if disp is None:
                raise RuntimeError(
                    f"IntentRegistry 未绑定 dispatcher，无法执行 action 绑定: {intent_name} -> {action_name}"
                )
            return disp.execute(action_name, *args, **kwargs)

        return _wrapper

    def meta(self, intent_name: str) -> Dict[str, Any]:
        b = self.get_binding(intent_name)
        return b.to_dict() if b else {}

    # -------------------------
    # 管理能力
    # -------------------------
    def unregister(self, intent_name: str) -> bool:
        with self._lock:
            existed = intent_name in self._bindings
            self._bindings.pop(intent_name, None)
        if existed:
            logger.info(f"❌ 注销意图: {intent_name}")
        return existed

    def list_intents(self, detailed: bool = False) -> List[Any]:
        with self._lock:
            if not detailed:
                return sorted(self._bindings.keys())
            return [b.to_dict() for b in self._bindings.values()]

    def all_intents(self) -> Dict[str, Callable]:
        with self._lock:
            keys = list(self._bindings.keys())
        return {k: self.get(k) for k in keys}  # type: ignore[return-value]

    # -------------------------
    # 魔术方法
    # -------------------------
    def __contains__(self, intent_name: str) -> bool:
        return self.has_intent(intent_name)

    def __getitem__(self, intent_name: str) -> Callable:
        fn = self.get(intent_name)
        if not fn:
            raise KeyError(intent_name)
        return fn