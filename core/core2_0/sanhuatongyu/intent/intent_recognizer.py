#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Pattern

logger = logging.getLogger("IntentRecognizer")


# =========================
# 企业级：规则结构
# =========================
@dataclass(order=True)
class IntentRule:
    # 只允许 priority 参与排序（避免 re.Pattern 参与比较导致崩溃）
    priority: int = field(default=0, compare=True)

    # 以下字段都不参与排序比较
    pattern: Pattern = field(default=None, compare=False)  # type: ignore
    intent: str = field(default="", compare=False)
    action_name: str = field(default="", compare=False)
    opts: Dict[str, Any] = field(default_factory=dict, compare=False)
    description: str = field(default="", compare=False)
    confidence: float = field(default=0.85, compare=False)
    risk: str = field(default="low", compare=False)               # low|medium|high
    need_confirm: bool = field(default=False, compare=False)

    def to_meta(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "action_name": self.action_name,
            "priority": self.priority,
            "confidence": self.confidence,
            "risk": self.risk,
            "need_confirm": self.need_confirm,
            "description": self.description,
            "pattern": getattr(self.pattern, "pattern", str(self.pattern)),
            "opts": dict(self.opts or {}),
        }


class IntentRecognizer:
    """
    三花聚顶 · 企业增强版 IntentRecognizer
    - 规则驱动 + 参数抽取
    - 稳定输出契约（可治理/可观测）
    - 预编译正则 + 优先级排序
    - 预留 YAML 热更新入口（可运营）
    """

    # 默认高风险动作（可按你项目扩展）
    HIGH_RISK_ACTIONS = {
        "shutdown", "reboot", "logout", "suspend",
        "system.shutdown", "system.reboot", "system.logout", "system.suspend",
        "close_app",
    }

    def __init__(self):
        self.rules: List[IntentRule] = []
        self._init_builtin_rules()

    # -------------------------
    # 规则初始化
    # -------------------------
    def _init_builtin_rules(self):
        """
        内建规则（兜底可用）。
        说明：priority 越大越先匹配（企业版推荐策略）
        """
        def R(pat: str,
              intent: str,
              action: str,
              opts: Optional[Dict[str, Any]] = None,
              *,
              priority: int = 100,
              confidence: float = 0.85,
              risk: str = "low",
              need_confirm: bool = False,
              desc: str = "") -> IntentRule:
            compiled = re.compile(pat, re.IGNORECASE)
            return IntentRule(
                priority=priority,
                pattern=compiled,
                intent=intent,
                action_name=action,
                opts=opts or {},
                description=desc,
                confidence=confidence,
                risk=risk,
                need_confirm=need_confirm,
            )

        # ====== 视频播放（更具体的优先）======
        self.rules.extend([
            R(r"播放[：:\s]*([^\s]+)\.(mp4|mkv|avi|mov)\b",
              "play_video_file", "play_video_file",
              {"extract": "video_ext"},
              priority=300, confidence=0.92, desc="播放指定扩展名视频"),

            R(r"播放[：:\s]*([^\s]+)(电影|视频)\b",
              "play_video_file", "play_video_file",
              {"extract": "video_cn_suffix"},
              priority=250, confidence=0.88, desc="播放中文后缀视频"),

            # 泛化兜底：播放xxx（风险：误把“播放音乐”也吃掉，所以优先级较低）
            R(r"播放[：:\s]*([^\s]+)\b",
              "play_video_file", "play_video_file",
              {"extract": "video_guess"},
              priority=120, confidence=0.70, desc="播放（兜底猜测为视频文件名）"),
        ])

        # ====== 音乐 ======
        self.rules.extend([
            R(r"播放(音乐|歌曲)\b", "play_music", "play_music", {},
              priority=260, confidence=0.92, desc="播放音乐"),
            R(r"下一(首|曲)\b", "next_song", "next_song", {},
              priority=220, confidence=0.90, desc="下一首"),
            R(r"上一(首|曲)\b", "previous_song", "previous_song", {},
              priority=220, confidence=0.90, desc="上一首"),
            R(r"暂停(音乐)?\b", "pause_music", "pause_music", {},
              priority=210, confidence=0.88, desc="暂停音乐"),
            R(r"停止(音乐)?\b", "stop_music", "stop_music", {},
              priority=210, confidence=0.88, desc="停止音乐"),
            R(r"(开启|打开)?单曲循环\b", "loop_one_on", "loop_one_on", {},
              priority=200, confidence=0.86, desc="开启单曲循环"),
            R(r"(关闭)?单曲循环\b", "loop_one_off", "loop_one_off", {},
              priority=200, confidence=0.82, desc="关闭单曲循环"),
        ])

        # ====== 蓝牙 ======
        self.rules.extend([
            R(r"打开(蓝牙)\b", "enable_bluetooth", "enable_bluetooth", {},
              priority=180, confidence=0.86, desc="打开蓝牙"),
            R(r"关闭(蓝牙)\b", "disable_bluetooth", "disable_bluetooth", {},
              priority=180, confidence=0.86, desc="关闭蓝牙"),
            R(r"连接(耳机|蓝牙耳机)\b", "connect_headset", "connect_headset", {},
              priority=170, confidence=0.82, desc="连接耳机"),
        ])

        # ====== 系统控制（高风险：默认确认）======
        self.rules.extend([
            R(r"(关机|关闭电脑|关闭助手|退出)\b", "shutdown", "shutdown", {},
              priority=500, confidence=0.95, risk="high", need_confirm=True, desc="关机/退出"),

            R(r"(重启|重新启动)(系统)?\b", "reboot", "reboot", {},
              priority=480, confidence=0.95, risk="high", need_confirm=True, desc="重启"),

            R(r"锁屏\b", "lock_screen", "lock_screen", {},
              priority=240, confidence=0.90, risk="medium", need_confirm=False, desc="锁屏"),

            R(r"(睡眠|待机)\b", "suspend", "suspend", {},
              priority=240, confidence=0.90, risk="high", need_confirm=True, desc="睡眠/待机"),

            R(r"注销\b", "logout", "logout", {},
              priority=240, confidence=0.90, risk="high", need_confirm=True, desc="注销"),

            R(r"关闭显示器\b", "turn_off_display", "turn_off_display", {},
              priority=200, confidence=0.86, desc="关闭显示器"),
        ])

        # ====== 工具 ======
        self.rules.extend([
            R(r"(截图|截屏)\b", "screenshot", "screenshot", {},
              priority=190, confidence=0.88, desc="截图"),
            R(r"打开(浏览器)\b", "open_browser", "open_browser", {},
              priority=190, confidence=0.88, desc="打开浏览器"),
            R(r"打开网址[：:\s]*(https?://[^\s]+)\b", "open_url", "open_url",
              {"extract": "url"},
              priority=210, confidence=0.92, desc="打开网址"),
            R(r"(当前)?时间\b", "show_time", "show_time", {},
              priority=160, confidence=0.80, desc="显示时间"),
            R(r"(当前)?日期\b", "show_date", "show_date", {},
              priority=160, confidence=0.80, desc="显示日期"),
            R(r"(检测|检查)网络\b", "check_network", "check_network", {},
              priority=160, confidence=0.80, desc="检测网络"),
            R(r"(天气|天气查询)\b", "weather_query", "weather_query", {},
              priority=150, confidence=0.75, desc="天气查询（示例）"),
            R(r"设置提醒[：:\s]*(\d+)\b", "set_reminder", "set_reminder",
              {"extract": "minutes"},
              priority=170, confidence=0.84, desc="设置提醒"),
        ])

        # ====== 关闭应用（中风险：建议确认）======
        self.rules.extend([
            R(r"关闭(浏览器|应用|[a-zA-Z0-9_\u4e00-\u9fa5]+)\b", "close_app", "close_app",
              {"extract": "app"},
              priority=320, confidence=0.90, risk="medium", need_confirm=True, desc="关闭应用"),
        ])

        # ====== 记忆（建议你后续在 AICore 注册 memory.search 动作）======
        self.rules.extend([
            R(r"记忆[:：]?(.*)$", "remember", "memory.add",
              {"extract": "memory_add"},
              priority=210, confidence=0.86, desc="写入记忆"),

            R(r"查询[:：]?(.*)$", "search", "memory.search",
              {"extract": "memory_search"},
              priority=200, confidence=0.80, desc="查询记忆（需实现 memory.search）"),
        ])

        # 排序：priority 高优先（现在不会再因为 pattern 比较崩溃）
        self.rules.sort(reverse=True)

    # -------------------------
    # 对外：动态加规则（企业运营入口）
    # -------------------------
    def add_rule(self,
                 pattern: str,
                 intent: str,
                 action_name: str,
                 opts: Optional[Dict[str, Any]] = None,
                 *,
                 priority: int = 100,
                 confidence: float = 0.85,
                 risk: str = "low",
                 need_confirm: bool = False,
                 desc: str = ""):
        compiled = re.compile(pattern, re.IGNORECASE)
        self.rules.append(IntentRule(
            priority=priority,
            pattern=compiled,
            intent=intent,
            action_name=action_name,
            opts=opts or {},
            description=desc,
            confidence=confidence,
            risk=risk,
            need_confirm=need_confirm,
        ))
        self.rules.sort(reverse=True)
        logger.info(f"✅ 新增规则: {intent} -> {action_name}, priority={priority}")

    # -------------------------
    # 规范化与抽参
    # -------------------------
    @staticmethod
    def _normalize_query(query: str) -> str:
        q = (query or "").strip()
        q = re.sub(r"\s+", " ", q)
        return q

    def _extract_params(self, rule: IntentRule, match: re.Match) -> Dict[str, Any]:
        opts = rule.opts or {}
        extract = opts.get("extract")

        params: Dict[str, Any] = {}

        if extract == "video_ext":
            filename = f"{match.group(1)}.{match.group(2)}"
            params["filepath"] = os.path.expanduser(f"~/视频/{filename}")

        elif extract == "video_cn_suffix":
            name = match.group(1)
            params["filepath"] = os.path.expanduser(f"~/视频/{name}.mp4")

        elif extract == "video_guess":
            name = match.group(1)
            if name in ("音乐", "歌曲"):
                return {}
            params["filepath"] = os.path.expanduser(f"~/视频/{name}.mp4")

        elif extract == "url":
            params["url"] = (match.group(1) or "").strip()

        elif extract == "minutes":
            try:
                params["minutes"] = int(match.group(1))
            except Exception:
                params["minutes"] = 1

        elif extract == "app":
            params["app_name"] = (match.group(1) or "").strip()

        elif extract == "memory_add":
            content = (match.group(1) or "").strip()
            params["category"] = "notes"
            params["content"] = content

        elif extract == "memory_search":
            keyword = (match.group(1) or "").strip()
            params["keyword"] = keyword

        else:
            gd = match.groupdict() if hasattr(match, "groupdict") else {}
            if gd:
                params.update(gd)

        return params

    # -------------------------
    # 企业级：稳定输出契约
    # -------------------------
    def recognize(self, query: str) -> Dict[str, Any]:
        q_raw = query
        q = self._normalize_query(query)
        if not q:
            return {"type": "none", "normalized_query": ""}

        for rule in self.rules:
            m = rule.pattern.search(q)
            if not m:
                continue

            params = self._extract_params(rule, m)

            risk = rule.risk
            need_confirm = rule.need_confirm
            if rule.action_name in self.HIGH_RISK_ACTIONS:
                risk = "high"
                need_confirm = True

            result = {
                "type": "intent",
                "intent": rule.intent,
                "action_name": rule.action_name,
                "params": params,
                "source": "rule",
                "confidence": float(rule.confidence),
                "risk": risk,
                "need_confirm": bool(need_confirm),
                "normalized_query": q,
                "match": {
                    "pattern": rule.pattern.pattern,
                    "groups": m.groups(),
                    "groupdict": m.groupdict(),
                    "matched_text": m.group(0),
                    "rule_meta": rule.to_meta(),
                },
            }

            logger.info(
                f"🎯 intent={rule.intent} -> action={rule.action_name} "
                f"risk={risk} confirm={need_confirm} params={params}"
            )
            return result

        logger.debug(f"❓ 未匹配任何意图: {q_raw}")
        return {"type": "none", "normalized_query": q}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ir = IntentRecognizer()

    tests = [
        "播放音乐",
        "播放 星球大战.mp4",
        "播放 星球大战电影",
        "关闭蓝牙",
        "关闭chrome",
        "关机",
        "重启系统",
        "锁屏",
        "打开网址:https://www.bing.com",
        "设置提醒:5",
        "记忆: 今天很开心",
        "查询: 小王",
        "未知命令",
    ]

    for t in tests:
        print("=" * 60)
        print("输入:", t)
        print("输出:", ir.recognize(t))