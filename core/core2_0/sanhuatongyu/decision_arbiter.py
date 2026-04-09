from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional

from core.core2_0.sanhuatongyu.suggestion_interpreter import (
    InterpretationResult,
    SuggestionItem,
)


# ============================================================
# 数据模型
# ============================================================

DEFAULT_BLOCKED_KEYWORDS = [
    "rm -rf",
    "mkfs",
    "dd if=",
    "poweroff",
    "shutdown",
    "halt",
    "reboot",
    "iptables -F",
]

PREVIEW_SAFE_PREFIXES = [
    "code_inserter.preview_",
]

WRITE_INTENT_KEYWORDS = [
    "写文件",
    "写入文件",
    "覆盖文件",
    "替换文件",
    "修改文件",
    "删除文件",
    "写配置",
    "覆盖配置",
    "替换配置",
    "修改配置",
    "apply patch",
    "apply changes",
    "overwrite",
    "replace",
    "write file",
    "edit file",
    "modify file",
]

NETWORK_CHANGE_KEYWORDS = [
    "改网络",
    "修改网络",
    "切换网络",
    "禁用网络",
    "启用网络",
    "修改 wifi",
    "修改蓝牙",
    "change network",
    "network config",
    "iptables",
    "ifconfig",
    "route add",
]

HIGH_RISK_KEYWORDS = [
    "rm -rf",
    "mkfs",
    "dd if=",
    "poweroff",
    "shutdown",
    "halt",
    "reboot",
    "iptables -F",
]


@dataclass
class ArbiterPolicy:
    allow_shell: bool = False
    allow_file_write: bool = False
    allow_network_change: bool = False
    min_confidence: float = 0.45
    force_review_on_high_risk: bool = True
    allowed_action_prefixes: List[str] = field(default_factory=list)
    blocked_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_KEYWORDS))
    reject_critical_commands: bool = True
    preview_safe_prefixes: List[str] = field(default_factory=lambda: list(PREVIEW_SAFE_PREFIXES))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # 保持对旧输出的兼容：不额外暴露 preview_safe_prefixes
        data.pop("preview_safe_prefixes", None)
        return data


@dataclass
class ArbiterDecision:
    approved_items: List[SuggestionItem] = field(default_factory=list)
    review_items: List[SuggestionItem] = field(default_factory=list)
    rejected_items: List[SuggestionItem] = field(default_factory=list)
    item_decisions: List[Dict[str, Any]] = field(default_factory=list)

    overall_verdict: str = "review"   # approve / review / reject / mixed
    risk_level: str = "low"           # low / medium / high
    reasons: List[str] = field(default_factory=list)
    policy_snapshot: Dict[str, Any] = field(default_factory=dict)

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        if item is None:
            return {}
        if hasattr(item, "to_dict") and callable(getattr(item, "to_dict")):
            try:
                return item.to_dict()
            except Exception:
                pass
        if is_dataclass(item):
            try:
                return asdict(item)
            except Exception:
                pass
        if hasattr(item, "__dict__"):
            try:
                return dict(vars(item))
            except Exception:
                pass
        return {"value": repr(item)}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved_items": [self._serialize_item(x) for x in self.approved_items],
            "review_items": [self._serialize_item(x) for x in self.review_items],
            "rejected_items": [self._serialize_item(x) for x in self.rejected_items],
            "item_decisions": list(self.item_decisions),
            "overall_verdict": self.overall_verdict,
            "risk_level": self.risk_level,
            "reasons": list(self.reasons),
            "policy_snapshot": dict(self.policy_snapshot),
        }


# ============================================================
# 裁决器
# ============================================================

class DecisionArbiter:
    def __init__(self, policy: Optional[ArbiterPolicy] = None) -> None:
        self.policy = policy or ArbiterPolicy()

    def arbitrate(
        self,
        interpretation: InterpretationResult,
        runtime_context: Optional[Dict[str, Any]] = None,
    ) -> ArbiterDecision:
        runtime_context = runtime_context or {}
        decision = ArbiterDecision(policy_snapshot=self.policy.to_dict())

        items = list(getattr(interpretation, "items", []) or [])
        if not items:
            decision.overall_verdict = "reject"
            decision.risk_level = "low"
            decision.reasons = ["未发现可裁决建议"]
            return decision

        max_risk = "low"

        for item in items:
            verdict, reasons = self._decide_item(item, runtime_context)

            item_risk = self._risk_of_item(item)
            max_risk = self._max_risk(max_risk, item_risk)

            decision.item_decisions.append(
                {
                    "item_id": getattr(item, "item_id", None),
                    "verdict": verdict,
                    "reasons": reasons,
                }
            )

            if verdict == "approve":
                decision.approved_items.append(item)
            elif verdict == "reject":
                decision.rejected_items.append(item)
            else:
                decision.review_items.append(item)

        if decision.rejected_items and not decision.approved_items and not decision.review_items:
            decision.overall_verdict = "reject"
        elif decision.approved_items and not decision.review_items and not decision.rejected_items:
            decision.overall_verdict = "approve"
        elif decision.review_items and not decision.approved_items and not decision.rejected_items:
            decision.overall_verdict = "review"
        else:
            decision.overall_verdict = "mixed"

        if decision.rejected_items:
            max_risk = self._max_risk(max_risk, "high")
        elif decision.review_items:
            max_risk = self._max_risk(max_risk, "medium")

        decision.risk_level = max_risk

        reasons: List[str] = []
        if decision.rejected_items:
            reasons.append("存在被策略拒绝的建议")
        if decision.review_items:
            reasons.append("存在需要人工复核/确认的建议")
        decision.reasons = reasons

        return decision

    # --------------------------------------------------------
    # 单项裁决
    # --------------------------------------------------------

    def _decide_item(
        self,
        item: SuggestionItem,
        runtime_context: Dict[str, Any],
    ) -> tuple[str, List[str]]:
        reasons: List[str] = []
        raw_text = str(getattr(item, "raw_text", "") or "")
        action_name = getattr(item, "action_name", None)
        command = str(getattr(item, "command", "") or "")
        confidence = float(getattr(item, "confidence", 0.0) or 0.0)
        kind = str(getattr(item, "kind", "") or "")
        requires_confirmation = bool(getattr(item, "requires_confirmation", False))
        manual_only = bool(getattr(item, "manual_only", False))

        merged_text = " | ".join(
            x for x in [raw_text, action_name or "", command] if x
        ).lower()

        # 1) 高危阻断关键词
        blocked = self._match_keywords(merged_text, self.policy.blocked_keywords)
        if blocked and self.policy.reject_critical_commands:
            reasons.append(f"命中阻断关键词: {blocked[0]}")
            return "reject", reasons

        # 2) 低置信度进入 review
        if confidence < self.policy.min_confidence:
            reasons.append(
                f"置信度低于阈值: {confidence:.2f} < {self.policy.min_confidence:.2f}"
            )
            return "review", reasons

        # 3) 明确人工项
        if kind == "manual" or manual_only or requires_confirmation:
            reasons.append("该建议只能进入人工执行/确认分支")
            return "review", reasons

        # 4) shell 限制
        if kind == "shell":
            if not self.policy.allow_shell:
                reasons.append("shell 执行当前策略未放行")
                return "review", reasons

            high_risk_shell = self._match_keywords(merged_text, HIGH_RISK_KEYWORDS)
            if high_risk_shell:
                reasons.append(f"shell 命中高风险关键词: {high_risk_shell[0]}")
                if self.policy.force_review_on_high_risk:
                    return "review", reasons

            reasons.append("通过当前策略裁决")
            return "approve", reasons

        # 5) action 白名单前缀
        if action_name:
            if self.policy.allowed_action_prefixes:
                if not self._matches_prefix(action_name, self.policy.allowed_action_prefixes):
                    reasons.append(f"action 不在允许前缀中: {action_name}")
                    return "review", reasons

            # 6) preview 动作豁免写入策略
            if self._is_preview_safe_action(action_name):
                reasons.append("preview 动作为只读预演，豁免写入限制")
                return "approve", reasons

            # 7) 非 preview 写入/覆盖策略
            if self._looks_like_file_write(item, merged_text):
                if not self.policy.allow_file_write:
                    reasons.append("建议涉及写文件/覆盖配置，当前策略未放行")
                    return "review", reasons

            # 8) 网络变更策略
            if self._looks_like_network_change(item, merged_text):
                if not self.policy.allow_network_change:
                    reasons.append("建议涉及网络变更，当前策略未放行")
                    return "review", reasons

            # 9) item 自带高风险标签
            if self.policy.force_review_on_high_risk and self._risk_of_item(item) == "high":
                reasons.append("建议自带高风险标签，进入人工复核")
                return "review", reasons

            reasons.append("通过当前策略裁决")
            return "approve", reasons

        # 10) 未识别但可执行性不明确，进入 review
        reasons.append("动作意图不明确，进入人工复核")
        return "review", reasons

    # --------------------------------------------------------
    # 规则辅助
    # --------------------------------------------------------

    def _matches_prefix(self, action_name: str, prefixes: List[str]) -> bool:
        for p in prefixes:
            if action_name == p or action_name.startswith(p):
                return True
        return False

    def _is_preview_safe_action(self, action_name: Optional[str]) -> bool:
        if not action_name:
            return False
        return self._matches_prefix(action_name, self.policy.preview_safe_prefixes)

    def _match_keywords(self, text: str, keywords: List[str]) -> List[str]:
        if not text:
            return []
        hits = []
        for kw in keywords:
            if kw and kw.lower() in text:
                hits.append(kw)
        return hits

    def _looks_like_file_write(self, item: SuggestionItem, merged_text: str) -> bool:
        action_name = getattr(item, "action_name", None)

        if self._is_preview_safe_action(action_name):
            return False

        if action_name:
            if action_name.startswith("code_inserter."):
                return True

        return bool(self._match_keywords(merged_text, WRITE_INTENT_KEYWORDS))

    def _looks_like_network_change(self, item: SuggestionItem, merged_text: str) -> bool:
        action_name = getattr(item, "action_name", None)

        if action_name and (
            action_name.startswith("system.net.")
            or action_name.startswith("sys.wifi.")
            or action_name.startswith("sys.bt.")
        ):
            return True

        return bool(self._match_keywords(merged_text, NETWORK_CHANGE_KEYWORDS))

    def _risk_of_item(self, item: SuggestionItem) -> str:
        risks = getattr(item, "risks", None) or []
        level = "low"
        for risk in risks:
            current = None
            if isinstance(risk, dict):
                current = str(risk.get("level", "") or "").lower()
            else:
                current = str(getattr(risk, "level", "") or "").lower()

            if current in ("high", "critical"):
                return "high"
            if current == "medium":
                level = "medium"
        return level

    def _max_risk(self, a: str, b: str) -> str:
        order = {"low": 0, "medium": 1, "high": 2}
        return a if order.get(a, 0) >= order.get(b, 0) else b
