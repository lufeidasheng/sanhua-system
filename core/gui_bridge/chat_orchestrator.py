#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .gui_memory_bridge import (
    append_action,
    append_chat,
    display_is_polluted,
    execute as mem_execute,
    extract_text,
    sanitize_reply_for_writeback,
    try_local_memory_answer,
)

_MODULE_DISPOSITION_RULES = [
    {
        "module": "audio_capture",
        "status": "DEGRADED",
        "reason": "spawn_pickle_thread_local",
        "problem_type": "macOS 已知兼容降级（spawn/pickle）",
        "solution": "可接受保持降级运行",
        "priority": "低",
        "blocking": "否（不阻塞主链）",
        "ticket": "否",
        "files": "modules/audio_capture/module.py",
        "strategy": "保留降级 + 标记为已知问题，后续单独排期治理",
    },
    {
        "module": "music_module",
        "status": "DEGRADED",
        "reason": "player_missing",
        "problem_type": "播放器依赖缺失导致能力降级",
        "solution": "可保持降级，不阻塞主链",
        "priority": "低",
        "blocking": "否",
        "ticket": "否",
        "files": "modules/music_module/module.py",
        "strategy": "安装 mpv/mplayer/ffplay/vlc 任一播放器后再恢复能力，后续单独治理",
    },
    {
        "module": "desktop_notify",
        "status": "DEGRADED",
        "reason": None,
        "problem_type": "通知后端不可用导致能力降级",
        "solution": "可接受降级到 stdout，不阻塞主链",
        "priority": "低",
        "blocking": "否",
        "ticket": "否",
        "files": "modules/desktop_notify/module.py",
        "strategy": "保持 stdout 降级输出，后续按平台条件单独治理",
    },
    {
        "module": "audio_consumer",
        "status": "STOPPED",
        "reason": None,
        "problem_type": "停止态/当前未运行",
        "solution": "若当前不依赖该能力，可保持停止",
        "priority": "低",
        "blocking": "否",
        "ticket": "否",
        "files": "modules/audio_consumer/module.py",
        "strategy": "保持停止态；需要该能力时再手动启动或单独排查",
    },
    {
        "module": None,
        "status": ("FAIL", "FAILED", "ERROR", "CRITICAL"),
        "reason": None,
        "problem_type": "模块异常",
        "solution": "优先检查模块依赖、初始化逻辑与运行日志",
        "priority": "高",
        "blocking": "是",
        "ticket": "是",
        "files": "需根据对应模块定位",
        "strategy": "先定位依赖/初始化失败点，再决定是否降级或替换",
    },
    {
        "module": None,
        "status": "DEGRADED",
        "reason": None,
        "problem_type": "能力降级",
        "solution": "保持降级运行，后续单独治理",
        "priority": "中",
        "blocking": "否",
        "strategy": "不阻塞主链，后续排期修复",
    },
    {
        "module": None,
        "status": "STOPPED",
        "reason": None,
        "problem_type": "停止态",
        "solution": "若当前不依赖该能力，可暂不处理；需要时再手动启动或单独排查",
        "priority": "低",
        "blocking": "否",
        "strategy": "保留停止态，按需启用",
    },
    {
        "module": None,
        "status": "UNKNOWN",
        "reason": None,
        "problem_type": "状态不明",
        "solution": "补充 health_check 或检查模块当前是否已启动",
        "priority": "中",
        "blocking": "否",
        "strategy": "先补充状态采集，再判断是否需要修复",
    },
]


def _build_module_disposition(
    name: str,
    status: str,
    reason: str,
    detail: Any,
    verbose: bool,
) -> str:
    for rule in _MODULE_DISPOSITION_RULES:
        rule_module = rule.get("module")
        if rule_module and rule_module != name:
            continue
        rule_status = rule.get("status")
        if rule_status:
            if isinstance(rule_status, (list, tuple, set)):
                if status not in rule_status:
                    continue
            elif status != rule_status:
                continue
        rule_reason = rule.get("reason")
        if rule_reason and rule_reason != reason:
            continue
        reason_text = reason or "当前未提供明确 reason"
        if not verbose:
            conclusion = rule.get("solution", "") or rule.get("strategy", "") or "建议后续排查"
            return "\n".join([
                f"模块：{name}",
                f"状态：{status}",
                f"结论：{conclusion}",
            ])
        block = [
            f"模块：{name}",
            f"状态：{status}",
            f"原因：{reason_text}",
            f"解决方案：{rule.get('solution', '')}",
            f"优先级：{rule.get('priority', '')}",
            f"是否阻塞主链：{rule.get('blocking', '')}",
            f"是否建议立刻开工单：{rule.get('ticket', '')}",
            f"建议修改文件：{rule.get('files', '')}",
            f"当前推荐策略：{rule.get('strategy', '')}",
        ]
        if detail and not reason:
            block.append(f"详情：{detail}")
        return "\n".join(block)
    return ""


class GUIChatOrchestrator:
    def __init__(
        self,
        ctx: Any,
        aicore: Any,
        action_caller: Callable[[str, dict], Any],
        list_actions: Callable[[], list],
        logger: Optional[Callable[[str], None]] = None,
        strip_protocol: Optional[Callable[[Any], str]] = None,
    ):
        self.ctx = ctx
        self.aicore = aicore
        self.action_caller = action_caller
        self.list_actions = list_actions
        self.logger = logger
        self.strip_protocol = strip_protocol or (lambda x: str(x or ""))

    def _log(self, text: str) -> None:
        if callable(self.logger):
            try:
                self.logger(text)
                return
            except Exception:
                pass
        print(text)

    def _extract_reply(self, obj: Any) -> str:
        try:
            text = extract_text(obj)
        except Exception:
            text = str(obj or "")
        text = self.strip_protocol(text)
        return str(text or "").strip()

    def _remember_local_turn(self, user_text: str, reply: str, kind: str) -> None:
        user_text = str(user_text or "").strip()
        reply = str(reply or "").strip()
        kind = str(kind or "").strip() or "local"
        ac = self.aicore

        if not reply:
            return

        try:
            need_append_user = True
            snapshot = mem_execute(ac, "memory.snapshot")
            if isinstance(snapshot, dict):
                snap = snapshot.get("snapshot") or {}
                session = ((snap.get("session_cache") or {}).get("active_session") or {})
                recent = session.get("recent_messages") or []
                for m in reversed(recent[-6:]):
                    if not isinstance(m, dict):
                        continue
                    if str(m.get("role") or "").strip() != "user":
                        continue
                    last_user = str(m.get("content") or "").strip()
                    if last_user == user_text:
                        need_append_user = False
                    break

            if need_append_user and user_text:
                append_chat(ac, "user", user_text)
        except Exception:
            pass

        try:
            append_chat(ac, "assistant", reply)
        except Exception:
            pass

        try:
            append_action(
                ac,
                f"gui.local_memory.{kind}",
                "success",
                reply[:200],
            )
        except Exception:
            pass

    def _try_local_memory(self, user_text: str) -> str:
        try:
            local = try_local_memory_answer(self.aicore, user_text)
        except Exception as e:
            self._log(f"⚠️ 本地记忆直答失败: {e}")
            return ""

        if local.get("ok"):
            reply = str(local.get("reply") or "").strip()
            kind = str(local.get("kind") or "local").strip()
            if reply:
                self._log(f"🧠 GUI local memory answer -> {kind}")
                self._remember_local_turn(user_text, reply, kind)
                return reply

        return ""

    def handle_chat(self, user_text: str) -> str:
        user_text = str(user_text or "").strip()
        if not user_text:
            return ""

        system_prompt = (
            "你是三花聚顶·聚核助手。请严格遵守以下输出规则：\n"
            "1. 只用中文回答\n"
            "2. 直接给出最终答案\n"
            "3. 不要输出思考过程\n"
            "4. 不要包含任何协议标记（如 <|channel|>, <|message|>, <think>, </think> 等）\n"
            "5. 不要包含任何分析、解释或内部思考\n"
            "6. 以纯文本形式输出"
        )

        # 0) 本地记忆短路（保持原语义不变）
        local_reply = self._try_local_memory(user_text)
        if local_reply:
            self._log("⚡ chat short-circuit -> local memory")
            return local_reply

        # 0.5) 模块原因/处置问答短路（短答/展开）
        q = user_text.replace("？", "?").replace("。", "").strip()
        sys_short_keys = ("系统检测", "打开系统检测", "系统状态", "检查系统状态", "健康检查")
        if any(k in q for k in sys_short_keys):
            try:
                self._log("🧭 chat short-circuit -> system.health_check [sys_detect]")
                health = self.action_caller("system.health_check", {})
                if isinstance(health, str):
                    return health
                try:
                    return json.dumps(health, ensure_ascii=False, indent=2)
                except Exception:
                    return str(health)
            except Exception as e:
                self._log(f"⚠️ system.health_check 短路失败: {e}")

        short_keys = ("怎么处理", "建议是什么", "解决方案", "要不要")
        verbose_keys = ("为什么", "原因", "为何", "详细", "具体", "优先级", "开工单", "改哪个文件", "展开")
        short_hit = any(k in q for k in short_keys)
        verbose_hit = any(k in q for k in verbose_keys)
        ask_disposition = short_hit or verbose_hit
        try:
            if ask_disposition:
                health = self.action_caller("system.health_check", {})
                modules = health.get("modules", {}) if isinstance(health, dict) else {}
                if isinstance(modules, dict):
                    hits = [name for name in modules.keys() if name and name in q]
                    if hits:
                        blocks = []
                        for hit in hits:
                            info = modules.get(hit) or {}
                            status = str(info.get("status") or info.get("health") or "UNKNOWN").strip().upper()
                            reason = str(info.get("reason") or "").strip()
                            detail = info.get("detail")
                            block = _build_module_disposition(hit, status, reason, detail, verbose=verbose_hit)
                            if block:
                                self._log("🧭 chat short-circuit -> system.health_check [disposition]")
                                blocks.append(block)
                        if blocks:
                            return "\n\n".join(blocks)
        except Exception as e:
            self._log(f"⚠️ system.health_check 短路失败: {e}")

        # 0.6) 模块状态/健康类问题短路
        if any(k in q for k in ("模块", "健康", "状态")) and any(
            k in q for k in ("正常", "异常", "未知", "降级", "健康", "状态")
        ):
            try:
                self._log("🧭 chat short-circuit -> system.health_check")
                health = self.action_caller("system.health_check", {})
                modules = health.get("modules", {}) if isinstance(health, dict) else {}
                if modules:
                    ok, warn, err, stopped, unk = [], [], [], [], []
                    for name, info in modules.items():
                        if not isinstance(info, dict):
                            unk.append(name)
                            continue
                        status = (info.get("status") or info.get("health") or "UNKNOWN")
                        status = str(status or "UNKNOWN").strip().upper()
                        if status in ("OK", "READY"):
                            ok.append(name)
                        elif status == "STOPPED":
                            stopped.append(name)
                        elif status in ("WARNING", "DEGRADED"):
                            warn.append(name)
                        elif status in ("ERROR", "CRITICAL", "FAILED"):
                            err.append(name)
                        else:
                            unk.append(name)

                    overall = (health.get("health") if isinstance(health, dict) else None) or health.get("status") if isinstance(health, dict) else None
                    overall = str(overall or "UNKNOWN").strip().upper()
                    parts = [f"系统健康：{overall}"]
                    if ok:
                        parts.append("正常模块：" + "、".join(ok))
                    if warn:
                        parts.append("警告/降级：" + "、".join(warn))
                    if err:
                        parts.append("异常模块：" + "、".join(err))
                    if stopped:
                        parts.append("停止模块：" + "、".join(stopped))
                    if unk:
                        parts.append("未知模块：" + "、".join(unk))
                    return "\n".join(parts)
            except Exception as e:
                self._log(f"⚠️ system.health_check 短路失败: {e}")

        # 1) ai.chat（正式主聊天桥）
        try:
            try:
                from core.core2_0.sanhuatongyu.services.model_engine.register_actions_llamacpp import (
                    ensure_ai_chat_actions_registered,
                )
                ensure_ai_chat_actions_registered()
            except Exception as e:
                self._log(f"⚠️ ai.chat 注册确保失败: {e}")
            self._log("🤖 chat route -> ai.chat")
            res = self.action_caller(
                "ai.chat",
                {
                    "query": user_text,
                    "prompt": user_text,
                    "message": user_text,
                    "text": user_text,
                    "system_prompt": system_prompt,
                    "system": system_prompt,
                },
            )
            reply = self._extract_reply(res)
            if reply:
                if display_is_polluted(reply):
                    self._log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")
                    local_reply = self._try_local_memory(user_text)
                    if local_reply:
                        return local_reply
                else:
                    sanitized = sanitize_reply_for_writeback(user_text, user_text, res)
                    if sanitized:
                        append_chat(self.aicore, "user", user_text)
                        append_chat(self.aicore, "assistant", sanitized)
                        append_action(self.aicore, "ai.chat", "success", sanitized[:200])
                    return reply
        except Exception as e:
            self._log(f"❌ ai.chat 失败: {e}")

        # 2) AICore.chat（内部 / 兜底桥）
        aicore_failed = False
        try:
            if self.aicore is not None:
                fn = getattr(self.aicore, "chat", None)
                if callable(fn):
                    self._log("🧠 chat route -> AICore.chat")
                    raw = fn(user_text)
                    reply = self._extract_reply(raw)
                    if reply:
                        if display_is_polluted(reply):
                            self._log("🧼 GUI display sanitize -> polluted AICore reply blocked [chat]")
                            local_reply = self._try_local_memory(user_text)
                            if local_reply:
                                return local_reply
                        else:
                            return reply
        except RecursionError:
            aicore_failed = True
            self._log("❌ AICore.chat 失败: recursion detected")
        except Exception as e:
            aicore_failed = True
            self._log(f"❌ AICore.chat 失败: {e}")

        # 3) aicore.chat（历史 action / 兼容兜底）
        if aicore_failed:
            self._log("⏭️ 已跳过 action:aicore.chat（避免自指回环）")
        else:
            try:
                self._log("🤖 chat route -> action:aicore.chat")
                res = self.action_caller(
                    "aicore.chat",
                    {
                        "query": user_text,
                        "prompt": user_text,
                        "message": user_text,
                        "text": user_text,
                    },
                )
                reply = self._extract_reply(res)
                if reply:
                    if display_is_polluted(reply):
                        self._log("🧼 GUI display sanitize -> polluted action:aicore.chat reply blocked")
                        local_reply = self._try_local_memory(user_text)
                        if local_reply:
                            return local_reply
                    else:
                        return reply
            except Exception as e:
                self._log(f"❌ aicore.chat 失败: {e}")

        # 4) AICore.ask（保留探测分支，不作为默认第一跳）
        try:
            if self.aicore is not None:
                fn = getattr(self.aicore, "ask", None)
                if callable(fn):
                    self._log("🧠 chat route -> AICore.ask [retained probe]")
                    raw = fn(user_text)
                    reply = self._extract_reply(raw)
                    if reply:
                        if display_is_polluted(reply):
                            self._log("🧼 GUI display sanitize -> polluted AICore reply blocked [ask]")
                            local_reply = self._try_local_memory(user_text)
                            if local_reply:
                                return local_reply
                        else:
                            return reply
        except RecursionError:
            self._log("❌ AICore.ask 失败: recursion detected")
        except Exception as e:
            self._log(f"❌ AICore.ask 失败: {e}")

        # 5) 最后再试一次本地记忆兜底
        local_reply = self._try_local_memory(user_text)
        if local_reply:
            return local_reply

        return "抱歉，我这次没有拿到有效回复。"
