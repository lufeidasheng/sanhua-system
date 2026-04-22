#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
三花聚顶 · QuantumActionDispatcher（企业旗舰版 v2.4.1-hardened）
支持：批量动作注册/中文alias/动态热加载/多模块生态/上下文注入/事件通知

企业增强（本次补齐关键能力）：
A) alias 未命中 → IntentRecognizer 规则识别兜底（intent->action_name）
   - 避免未匹配直接落到 LLM 胡编
   - 注意：这里不直接 import ActionSynthesizer（会与 ACTION_MANAGER 循环依赖）
B) aliases.yaml 兼容两种格式：
   - list 格式：[{name, keywords, function}]（你项目当前在用）
   - dict 格式：{alias: action}
"""

from __future__ import annotations

import threading
import inspect
import yaml
import os
from typing import Callable, Dict, List, Optional, Any, Union
from datetime import datetime
from difflib import get_close_matches

from core.core2_0.sanhuatongyu.logger import get_logger

log = get_logger("QuantumActionDispatcher")


# =========================
# 动作元数据（企业化）
# =========================
class ActionMeta:
    def __init__(
        self,
        name: str,
        func: Callable,
        description: str = "",
        permission: str = "user",
        module: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.func = func
        self.description = description
        self.permission = permission or "user"
        self.module = module or "core"
        self.extra = extra or {}
        self.register_time = datetime.now()

        # 企业治理字段（推荐放入 extra，但这里做标准化读取）
        self.risk = str(self.extra.get("risk", "low") or "low")
        self.need_confirm = bool(self.extra.get("need_confirm", False))

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission,
            "module": self.module,
            "extra": self.extra,
            "risk": self.risk,
            "need_confirm": self.need_confirm,
            "register_time": self.register_time.isoformat(),
        }


# =========================
# 主调度器（单例）
# =========================
class QuantumActionDispatcher:
    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._actions: Dict[str, ActionMeta] = {}
        self._action_aliases: Dict[str, str] = {}  # alias(中文/短语) -> action_name
        self._actions_lock = threading.RLock()
        self.context = None
        self._initialized = True

        # intent fallback（lazy init，避免循环依赖/启动成本）
        self._intent_recognizer = None
        self._intent_lock = threading.RLock()

        log.info("✅ QuantumActionDispatcher 初始化完成（hardened + intent-fallback-ready）")

    # =========================
    # context 注入
    # =========================
    def set_context(self, context: Any):
        self.context = context
        log.info(f"🌸 绑定主控 context: {type(context)}")

    # =========================
    # 注册/注销/查询
    # =========================
    def register_action(
        self,
        name: str,
        func: Callable,
        description: str = "",
        permission: str = "user",
        module: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        if not name or not isinstance(name, str):
            raise ValueError("action name 必须是非空字符串")
        if not callable(func):
            raise ValueError(f"action func 不可调用: {name}")

        with self._actions_lock:
            self._actions[name] = ActionMeta(
                name=name,
                func=func,
                description=description,
                permission=permission,
                module=module,
                extra=extra,
            )
        log.info(f"✅ 注册动作: {name} (模块: {module or 'core'})")

    def unregister_action(self, name: str):
        with self._actions_lock:
            if self._actions.pop(name, None):
                log.info(f"❌ 注销动作: {name}")
            else:
                log.warning(f"⚠️ 注销失败，未找到动作: {name}")

    def clear_actions_by_module(self, module_name: str) -> int:
        with self._actions_lock:
            to_remove = [n for n, m in self._actions.items() if m.module == module_name]
            for name in to_remove:
                self._actions.pop(name, None)
            log.info(f"模块 {module_name} 清理动作: {to_remove}")
            return len(to_remove)

    def get_action(self, name: str) -> Optional[ActionMeta]:
        with self._actions_lock:
            return self._actions.get(name)

    def list_actions(self, module: Optional[str] = None, detailed: bool = False) -> List[Any]:
        with self._actions_lock:
            items = []
            for a in self._actions.values():
                if module is not None and a.module != module:
                    continue
                items.append(a.to_dict() if detailed else a.name)
            return items

    # =========================
    # 企业硬化：kwargs 签名过滤
    # =========================
    @staticmethod
    def _filter_kwargs_by_signature(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            sig = inspect.signature(func)
            params = sig.parameters
            accepts_varkw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in params.values()
            )
            if accepts_varkw:
                return kwargs

            allowed = {k: v for k, v in kwargs.items() if k in params}
            return allowed
        except Exception:
            return kwargs

    @staticmethod
    def _is_bound_method(func: Callable) -> bool:
        return bool(getattr(func, "__self__", None))

    # =========================
    # 执行（企业统一入口）
    # =========================
    def call_action(self, name: str, params: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        live 主链标准入口。
        统一口径：context.call_action(name, params=...) -> dispatcher.call_action(...) -> execute(...)
        """
        payload: Dict[str, Any] = {}
        if isinstance(params, dict):
            payload.update(params)
        payload.update(kwargs)
        return self.execute(name, params=payload)

    def dispatch_action(self, name: str, params: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        历史兼容入口。
        保留桥接语义，避免被继续当成新的 live 主链真相源。
        """
        log.warning(f"⚠️ dispatch_action 为兼容入口，请优先改用 call_action: {name}")
        return self.call_action(name, params=params, **kwargs)

    def execute(self, name: str, *args, **kwargs) -> Any:
        with self._actions_lock:
            meta = self._actions.get(name)
            if not meta:
                raise KeyError(f"未知动作: {name}")

        func = meta.func

        try:
            sig = inspect.signature(func)
            param_names = list(sig.parameters)

            safe_kwargs = self._filter_kwargs_by_signature(func, dict(kwargs))

            if not param_names:
                return func(*args, **safe_kwargs)

            first_name = param_names[0]

            if first_name == "self" and self._is_bound_method(func):
                return func(*args, **safe_kwargs)

            if first_name in ("context", "ctx", "master", "c"):
                return func(self.context, *args, **safe_kwargs)

            return func(*args, **safe_kwargs)

        except Exception as e:
            log.error(f"💥 执行动作异常 {name}: {e}")
            raise

    # =========================
    # 执行并事件通知（兼容旧入口）
    # =========================
    def execute_action_and_notify(self, func, name: str, query: str, args: List[Any]):
        try:
            if self.context and hasattr(self.context, "event_bus"):
                self.context.event_bus.publish(f"{name}.start", {"query": query})

            result = func(self.context, query, *args)

            if self.context and hasattr(self.context, "event_bus"):
                self.context.event_bus.publish(f"{name}.success", {"query": query, "result": result})
            return result
        except Exception as e:
            log.error(f"❌ execute_action_and_notify 执行失败: {e}")
            if self.context and hasattr(self.context, "event_bus"):
                self.context.event_bus.publish(f"{name}.failure", {"query": query, "error": str(e)})
            return f"❌ 执行动作失败: {e}"

    # =========================
    # alias 管理
    # =========================
    def register_alias(self, keywords: Union[str, List[str]], action_name: str):
        if isinstance(keywords, str):
            keywords = [keywords]
        for k in keywords:
            kk = (k or "").strip()
            if not kk:
                continue
            self._action_aliases[kk] = (action_name or "").strip()
            log.info(f"📌 注册别名: '{kk}' → {(action_name or '').strip()}")

    def register_aliases(self, alias_map: Dict[str, List[str]]):
        """alias_map: {动作名: [alias1, alias2, ...]}"""
        for action, aliases in alias_map.items():
            self.register_alias(aliases, action)

    def get_aliases_for_action(self, name: str) -> List[str]:
        return [k for k, v in self._action_aliases.items() if v == name]

    def get_all_aliases(self) -> Dict[str, str]:
        return dict(self._action_aliases)

    # =========================
    # intent fallback（核心）
    # =========================
    def _ensure_intent_recognizer(self):
        """
        Lazy import，避免循环依赖/启动成本：
        - 只引 IntentRecognizer（它不依赖 ACTION_MANAGER）
        """
        with self._intent_lock:
            if self._intent_recognizer is not None:
                return self._intent_recognizer
            try:
                from core.core2_0.sanhuatongyu.intent.intent_recognizer import IntentRecognizer
                self._intent_recognizer = IntentRecognizer()
                log.info("✅ IntentRecognizer 已接入 QuantumActionDispatcher（fallback-ready）")
            except Exception as e:
                self._intent_recognizer = False  # 标记不可用
                log.warning(f"⚠️ IntentRecognizer 导入失败，intent fallback 禁用: {e}")
            return self._intent_recognizer

    def _try_intent_fallback(self, query: str) -> Optional[Dict[str, Any]]:
        ir = self._ensure_intent_recognizer()
        if not ir or ir is False:
            return None

        try:
            intent_obj = ir.recognize(query)
            if not isinstance(intent_obj, dict):
                return None
            if intent_obj.get("type") != "intent":
                return None

            action_name = (intent_obj.get("action_name") or "").strip()
            params = intent_obj.get("params") or {}
            risk = intent_obj.get("risk", "low")
            need_confirm = bool(intent_obj.get("need_confirm", False))

            if not action_name:
                return None

            with self._actions_lock:
                meta = self._actions.get(action_name)

            if not meta:
                # intent 识别到了，但动作没注册：返回 None，让上层走 LLM
                log.warning(f"⚠️ intent 命中但动作未注册: intent={intent_obj.get('intent')} action={action_name}")
                return None

            # 以 dispatcher.meta.extra 为准（企业治理主路径）
            # intent 给的 risk/need_confirm 作为补充
            mm = meta.to_dict()
            mm["risk"] = mm.get("risk") or risk
            mm["need_confirm"] = bool(mm.get("need_confirm")) or need_confirm

            log.info(f"🎯 intent fallback 命中: {intent_obj.get('intent')} → {action_name} params={params}")
            return {
                "name": action_name,
                "function": meta.func,
                "meta": mm,
                "params": params,
                "source": "intent",
            }

        except Exception as e:
            log.warning(f"⚠️ intent fallback 异常（忽略并回退其他路径）: {e}")
            return None

    # =========================
    # alias 匹配（增强：intent fallback）
    # =========================
    def match_action(self, query: str) -> Optional[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return None

        with self._actions_lock:
            # 1) 精确别名
            for keyword, name in self._action_aliases.items():
                if keyword.strip() == q and name in self._actions:
                    meta = self._actions[name]
                    log.info(f"✅ alias 精确命中: {keyword} → {name}")
                    return {"name": name, "function": meta.func, "meta": meta.to_dict(), "params": {}, "source": "alias_exact"}

            # 2) 模糊别名（包含匹配）
            for keyword, name in self._action_aliases.items():
                if keyword and (keyword in q) and name in self._actions:
                    meta = self._actions[name]
                    log.info(f"🔍 alias 模糊命中: {keyword} → {name}")
                    return {"name": name, "function": meta.func, "meta": meta.to_dict(), "params": {}, "source": "alias_fuzzy"}

            # 3) fallback：模糊动作名
            fallback = self._fuzzy_match(q)
            if fallback and fallback in self._actions:
                meta = self._actions[fallback]
                log.info(f"🪂 action 名模糊命中: {fallback}")
                return {"name": fallback, "function": meta.func, "meta": meta.to_dict(), "params": {}, "source": "action_fuzzy"}

        # 4) ✅ 企业关键：intent fallback（不持锁，避免锁重入）
        intent_hit = self._try_intent_fallback(q)
        if intent_hit:
            return intent_hit

        log.warning(f"❓ 未匹配动作: {q}")
        return None

    def _fuzzy_match(self, query: str) -> Optional[str]:
        with self._actions_lock:
            names = list(self._actions.keys())
        match = get_close_matches(query.strip(), names, n=1, cutoff=0.7)
        return match[0] if match else None

    # =========================
    # aliases.yaml 动态热加载（企业推荐）
    # 兼容两种格式：
    # A) list: [{name, keywords, function}]
    # B) dict: {alias: action}
    # =========================
    def load_aliases_yaml(self, path: str = "config/aliases.yaml"):
        if not os.path.isfile(path):
            log.warning(f"⚠️ 未找到 aliases.yaml 文件: {path}")
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # --- 格式 A：list ---
        if isinstance(data, list):
            loaded = 0
            for item in data:
                if not isinstance(item, dict):
                    continue
                action = (item.get("function") or item.get("action") or item.get("name") or "").strip()
                keywords = item.get("keywords") or []
                if not action or not keywords:
                    continue
                self.register_alias(keywords, action)
                loaded += len(keywords)
            log.info(f"✅ 成功加载 aliases.yaml(list)，已注册 {loaded} 条 alias")
            return {"format": "list", "count": loaded}

        # --- 格式 B：dict(alias -> action) ---
        if isinstance(data, dict):
            alias_map: Dict[str, List[str]] = {}
            for alias, action in data.items():
                if not alias or not action:
                    continue
                alias_map.setdefault(str(action).strip(), []).append(str(alias).strip())
            self.register_aliases(alias_map)
            log.info(f"✅ 成功加载 aliases.yaml(dict)，已注册 {sum(len(v) for v in alias_map.values())} 个 alias")
            return {"format": "dict", "count": sum(len(v) for v in alias_map.values())}

        log.warning(f"⚠️ aliases.yaml 格式不支持: {type(data)}（应为 list 或 dict）")
        return None

    def reload_aliases(self, path: str = "config/aliases.yaml"):
        self._action_aliases.clear()
        return self.load_aliases_yaml(path)


# ==== 单例导出 ====
dispatcher = QuantumActionDispatcher()
ACTION_MANAGER = dispatcher
