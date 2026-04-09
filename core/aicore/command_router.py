#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
from typing import Any, Dict, Tuple, Optional, Callable, List
from dataclasses import dataclass, field
import yaml

logger = logging.getLogger("CommandRouter")


# ================= Intent =================

@dataclass
class Intent:
    """三花聚顶 · 结构化意图定义"""
    name: str
    keywords: List[str]
    function: Optional[str] = None
    description: str = ""
    priority: int = 0
    params: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    module: Optional[str] = None
    lang: str = "zh-CN"

    def __post_init__(self):
        self.keywords = [kw.lower() for kw in self.keywords]


# ================= Router =================

class CommandRouter:
    """
    🌸 三花聚顶 · 指令路由器（稳定协议版）

    只负责：
    - 判断“是不是命令/意图”
    - 解析参数
    - 给出【结构化路由结果】

    不负责：
    - 执行
    - 状态持久化
    """

    def __init__(self, config_path: Optional[str] = None, lang: str = "zh-CN"):
        self._intents: List[Intent] = []
        self._regex_patterns: List[Tuple[re.Pattern, str]] = []
        self._custom_matchers: List[Tuple[Callable, str, int]] = []
        self.lang = lang
        self._context = None

        self._initialize_default_intents()
        if config_path:
            self.load_config(config_path)

    # ---------- context ----------

    def inject_context_manager(self, context):
        self._context = context

    # ---------- register ----------

    def register_intent(self, intent: Intent) -> None:
        self._intents.append(intent)
        self._intents.sort(key=lambda x: x.priority, reverse=True)

    def register_regex_intent(self, pattern: str, intent_name: str) -> None:
        self._regex_patterns.append((re.compile(pattern, re.IGNORECASE), intent_name))

    def register_custom_matcher(
        self,
        matcher: Callable[[str, Optional[Any]], Optional[Tuple[str, Dict]]],
        desc: str = "",
        priority: int = 100
    ):
        self._custom_matchers.append((matcher, desc, priority))
        self._custom_matchers.sort(key=lambda x: x[2], reverse=True)

    # ---------- load ----------

    def load_config(self, config_path: str) -> bool:
        try:
            data = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
            for item in data.get("intents", []):
                self.register_intent(Intent(**item))
            for pat, name in data.get("regex_intents", []):
                self.register_regex_intent(pat, name)
            return True
        except Exception as e:
            logger.error(f"配置加载失败: {e}", exc_info=True)
            return False

    # ---------- route ----------

    def route(self, query: str, last_intent: Optional[Intent] = None) -> Dict[str, Any]:
        """
        返回统一路由结果：
        {
          type: intent | none
          name
          function
          params
          source
          confidence
        }
        """
        if not isinstance(query, str) or not query.strip():
            return {"type": "none"}

        q = query.strip().lower()

        # 1. custom matcher
        for matcher, desc, _ in self._custom_matchers:
            try:
                result = matcher(q, self._context)
                if result:
                    name, params = result
                    intent = self._get_intent(name)
                    if intent:
                        return self._build_result(intent, params, "custom", 0.95)
            except Exception as e:
                logger.warning(f"matcher 异常 {desc}: {e}")

        # 2. regex
        for pat, name in self._regex_patterns:
            m = pat.search(q)
            if m:
                intent = self._get_intent(name)
                if intent:
                    return self._build_result(
                        intent,
                        m.groupdict() or {"match": m.group()},
                        "regex",
                        0.9,
                    )

        # 3. keyword
        for intent in self._intents:
            if not intent.enabled:
                continue
            for kw in intent.keywords:
                if kw in q:
                    return self._build_result(intent, {}, "keyword", 0.8)

        # 4. fuzzy continuation
        if last_intent:
            for k in ("继续", "再来", "重复"):
                if k in q:
                    return self._build_result(last_intent, {"fuzzy": True}, "fuzzy", 0.6)

        return {"type": "none"}

    # ---------- helpers ----------

    def _get_intent(self, name: str) -> Optional[Intent]:
        return next((i for i in self._intents if i.name == name), None)

    def _build_result(
        self,
        intent: Intent,
        params: Dict[str, Any],
        source: str,
        confidence: float
    ) -> Dict[str, Any]:
        return {
            "type": "intent",
            "name": intent.name,
            "function": intent.function,
            "module": intent.module,
            "priority": intent.priority,
            "params": params,
            "source": source,
            "confidence": confidence,
            "intent": intent,   # 内部保留
        }

    # ---------- defaults ----------

    def _initialize_default_intents(self):
        self.register_intent(
            Intent(
                name="shutdown",
                keywords=["关机", "关闭电脑"],
                function="shutdown_system",
                priority=10,
                module="system",
            )
        )