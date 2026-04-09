from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class RiskSignal:
    code: str
    level: str  # low / medium / high / critical
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SuggestionItem:
    item_id: str
    raw_text: str
    kind: str  # action / shell / manual / info / unknown
    action_name: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    command: Optional[str] = None
    confidence: float = 0.5
    reasons: List[str] = field(default_factory=list)
    risks: List[RiskSignal] = field(default_factory=list)
    requires_confirmation: bool = False
    manual_only: bool = False
    source: str = "heuristic"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["risks"] = [r.to_dict() for r in self.risks]
        return data


@dataclass
class InterpretationResult:
    raw_text: str
    normalized_text: str
    source: str
    items: List[SuggestionItem] = field(default_factory=list)
    global_risks: List[RiskSignal] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    is_actionable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "source": self.source,
            "items": [item.to_dict() for item in self.items],
            "global_risks": [r.to_dict() for r in self.global_risks],
            "metadata": self.metadata,
            "summary": self.summary,
            "is_actionable": self.is_actionable,
        }


# ============================================================
# 解释器
# ============================================================

class SuggestionInterpreter:
    """
    第一版目标：
    1. 能吃 LLM 返回的建议文本
    2. 尽量从 JSON / markdown / bullet list 中提取结构化建议
    3. 给后续 decision_arbiter / execution_planner 提供统一输入
    """

    ACTION_NAME_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
    KEY_VALUE_RE = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*([^\s,，;；]+)")
    BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s*(.+?)\s*$")

    HIGH_RISK_KEYWORDS = [
        "rm -rf",
        "mkfs",
        "dd if=",
        "reboot",
        "poweroff",
        "shutdown",
        "格式化",
        "删除",
        "清空",
        "覆盖",
        "kill -9",
        "iptables",
        "systemctl stop",
        "systemctl disable",
    ]

    MEDIUM_RISK_KEYWORDS = [
        "sudo",
        "pip install",
        "brew install",
        "dnf install",
        "apt install",
        "写入",
        "修改",
        "保存配置",
        "替换文件",
        "mv ",
        "cp ",
        "chmod",
        "chown",
        "连接网络",
        "切换模型",
    ]

    IMPERATIVE_HINTS = [
        "执行",
        "调用",
        "运行",
        "创建",
        "删除",
        "修改",
        "安装",
        "重启",
        "关闭",
        "打开",
        "发送",
        "连接",
        "断开",
        "切换",
        "保存",
        "写入",
        "生成",
        "触发",
    ]

    def interpret(
        self,
        text: str,
        source: str = "llm",
        context: Optional[Dict[str, Any]] = None,
    ) -> InterpretationResult:
        context = context or {}
        normalized = self._normalize_text(text)

        result = InterpretationResult(
            raw_text=text,
            normalized_text=normalized,
            source=source,
            metadata={"context": context},
        )

        items = self._parse_json_contract(normalized)
        if not items:
            items = self._parse_bullets_and_sentences(normalized)

        if not items and normalized.strip():
            single = self._parse_single_line(normalized.strip(), "single-1")
            if single:
                items.append(single)

        for item in items:
            self._attach_risks(item)

        result.items = items
        result.global_risks = self._collect_global_risks(items)
        result.is_actionable = any(i.kind in {"action", "shell", "manual"} for i in items)
        result.summary = self._build_summary(items)

        return result

    # --------------------------------------------------------
    # 解析层
    # --------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()

    def _parse_json_contract(self, text: str) -> List[SuggestionItem]:
        candidates = self._extract_possible_json_blocks(text)
        for block in candidates:
            try:
                payload = json.loads(block)
            except Exception:
                continue

            items = self._convert_json_payload_to_items(payload)
            if items:
                return items
        return []

    def _extract_possible_json_blocks(self, text: str) -> List[str]:
        blocks: List[str] = []

        fenced = re.findall(r"```json\s*(.*?)```", text, flags=re.S | re.I)
        blocks.extend([b.strip() for b in fenced if b.strip()])

        if text.startswith("{") or text.startswith("["):
            blocks.append(text)

        return blocks

    def _convert_json_payload_to_items(self, payload: Any) -> List[SuggestionItem]:
        raw_items: List[Dict[str, Any]] = []

        if isinstance(payload, list):
            raw_items = [x for x in payload if isinstance(x, dict)]
        elif isinstance(payload, dict):
            for key in ("suggestions", "actions", "steps", "plan"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_items = [x for x in value if isinstance(x, dict)]
                    break
            if not raw_items and any(k in payload for k in ("kind", "type", "action_name", "command")):
                raw_items = [payload]

        items: List[SuggestionItem] = []
        for idx, item in enumerate(raw_items, start=1):
            kind = str(item.get("kind") or item.get("type") or "").strip().lower()
            action_name = item.get("action_name") or item.get("action")
            command = item.get("command")
            raw_text = str(item.get("raw_text") or item.get("text") or item.get("reason") or item)

            if not kind:
                if action_name:
                    kind = "action"
                elif command:
                    kind = "shell"
                else:
                    kind = "unknown"

            suggestion = SuggestionItem(
                item_id=f"json-{idx}",
                raw_text=raw_text,
                kind=kind,
                action_name=str(action_name).strip() if action_name else None,
                params=item.get("params") if isinstance(item.get("params"), dict) else {},
                command=str(command).strip() if command else None,
                confidence=self._safe_confidence(item.get("confidence"), default=0.75),
                reasons=self._safe_list(item.get("reasons")),
                requires_confirmation=bool(item.get("requires_confirmation", False)),
                manual_only=bool(item.get("manual_only", False)),
                source="json",
            )
            items.append(suggestion)

        return items

    def _parse_bullets_and_sentences(self, text: str) -> List[SuggestionItem]:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        extracted: List[str] = []

        for line in lines:
            m = self.BULLET_RE.match(line)
            if m:
                extracted.append(m.group(1).strip())

        if not extracted:
            extracted = [line for line in lines if self._looks_action_like(line)]

        items: List[SuggestionItem] = []
        for idx, line in enumerate(extracted, start=1):
            item = self._parse_single_line(line, f"heuristic-{idx}")
            if item:
                items.append(item)
        return items

    def _parse_single_line(self, line: str, item_id: str) -> Optional[SuggestionItem]:
        action_name = self._extract_action_name(line)
        command = self._extract_shell_command(line)
        params = self._extract_params(line)

        if action_name:
            return SuggestionItem(
                item_id=item_id,
                raw_text=line,
                kind="action",
                action_name=action_name,
                params=params,
                confidence=0.72,
                reasons=["检测到 action 命名模式"],
                source="heuristic",
            )

        if command:
            return SuggestionItem(
                item_id=item_id,
                raw_text=line,
                kind="shell",
                command=command,
                params=params,
                confidence=0.68,
                reasons=["检测到 shell/命令行模式"],
                requires_confirmation=True,
                source="heuristic",
            )

        if self._looks_action_like(line):
            return SuggestionItem(
                item_id=item_id,
                raw_text=line,
                kind="manual",
                params=params,
                confidence=0.55,
                reasons=["检测到动作意图，但未能定位明确 action_name"],
                requires_confirmation=True,
                manual_only=True,
                source="heuristic",
            )

        return None

    # --------------------------------------------------------
    # 提取器
    # --------------------------------------------------------

    def _extract_action_name(self, text: str) -> Optional[str]:
        m = self.ACTION_NAME_RE.search(text)
        return m.group(1) if m else None

    def _extract_params(self, text: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for key, value in self.KEY_VALUE_RE.findall(text):
            params[key] = value
        return params

    def _extract_shell_command(self, text: str) -> Optional[str]:
        shell_hints = [
            "python ",
            "python3 ",
            "pip ",
            "pip3 ",
            "brew ",
            "dnf ",
            "apt ",
            "rm ",
            "mv ",
            "cp ",
            "chmod ",
            "chown ",
            "systemctl ",
            "curl ",
            "wget ",
            "git ",
            "ollama ",
        ]
        lower = text.lower()
        for hint in shell_hints:
            if hint in lower:
                return text
        return None

    def _looks_action_like(self, text: str) -> bool:
        if self._extract_action_name(text) or self._extract_shell_command(text):
            return True
        return any(k in text for k in self.IMPERATIVE_HINTS)

    # --------------------------------------------------------
    # 风险层
    # --------------------------------------------------------

    def _attach_risks(self, item: SuggestionItem) -> None:
        text = " ".join(
            [
                item.raw_text or "",
                item.action_name or "",
                item.command or "",
            ]
        ).lower()

        for kw in self.HIGH_RISK_KEYWORDS:
            if kw.lower() in text:
                item.risks.append(
                    RiskSignal(
                        code="HIGH_RISK_KEYWORD",
                        level="high",
                        message=f"检测到高风险关键词: {kw}",
                    )
                )
                item.requires_confirmation = True

        for kw in self.MEDIUM_RISK_KEYWORDS:
            if kw.lower() in text:
                item.risks.append(
                    RiskSignal(
                        code="MEDIUM_RISK_KEYWORD",
                        level="medium",
                        message=f"检测到中风险关键词: {kw}",
                    )
                )

        if item.kind == "shell":
            item.risks.append(
                RiskSignal(
                    code="SHELL_EXECUTION",
                    level="medium",
                    message="建议包含 shell 执行，默认需要额外裁决",
                )
            )
            item.requires_confirmation = True

    def _collect_global_risks(self, items: List[SuggestionItem]) -> List[RiskSignal]:
        out: List[RiskSignal] = []
        if not items:
            out.append(
                RiskSignal(
                    code="NO_ACTIONABLE_SUGGESTION",
                    level="low",
                    message="未提取到可执行建议",
                )
            )
        return out

    def _build_summary(self, items: List[SuggestionItem]) -> str:
        if not items:
            return "未识别到可执行建议。"
        parts = []
        for item in items:
            target = item.action_name or item.command or item.raw_text
            parts.append(f"{item.kind}:{target}")
        return " | ".join(parts)

    # --------------------------------------------------------
    # 工具函数
    # --------------------------------------------------------

    def _safe_confidence(self, value: Any, default: float = 0.5) -> float:
        try:
            value = float(value)
            return max(0.0, min(1.0, value))
        except Exception:
            return default

    def _safe_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(x) for x in value]
        if value is None:
            return []
        return [str(value)]
