#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
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


def _is_assistant_identity_question(q: str) -> bool:
    if "我是谁" in q:
        return False
    return q in {"你是谁", "你是什么", "介绍一下你自己"} or "你是谁?" in q


def _is_capability_question(q: str) -> bool:
    keys = (
        "你可以做什么",
        "你可以做啥",
        "你能做什么",
        "你能帮我做什么",
        "你都能干啥",
        "你会做什么",
        "你会啥",
        "你有什么功能",
        "你有哪些功能",
        "当前有哪些能力",
        "现在有哪些能力",
        "有哪些能力",
        "还能做啥",
        "还有呢",
        "还有啥",
    )
    return any(k in q for k in keys)


def _runtime_truth_question_kind(q: str) -> str:
    if any(k in q for k in ("当前模型路径", "模型路径", "模型文件", "模型在哪")):
        return "model_path"
    if any(k in q for k in ("当前后端", "现在后端", "当前用的后端", "后端是什么", "用的什么后端")):
        return "backend"
    if any(k in q for k in ("当前模型", "现在模型", "当前用的模型", "模型是什么", "用的什么模型")):
        return "model"
    return ""


def _classify_chat_route(q: str) -> dict[str, Any]:
    """Classify deterministic chat routes before the ai.chat fallback."""
    # Sysmon owns monitoring-state questions. Keep it ahead of generic health
    # terms like "状态" so monitoring requests cannot drift into health_check.
    sysmon_status_keys = ("系统监控状态", "监控状态怎么样", "sysmon 状态", "sysmon状态")
    if any(k in q for k in sysmon_status_keys):
        return {
            "route": "sysmon.status",
            "source": "sysmon.status",
            "short_circuit": True,
            "intent": "summary",
        }

    truth_kind = _runtime_truth_question_kind(q)
    if truth_kind:
        return {
            "route": "runtime.model_truth",
            "source": "aicore.get_status",
            "short_circuit": True,
            "intent": truth_kind,
        }

    # Health owns system/module health, abnormal, and handling-suggestion
    # questions. These must not fall through to sysmon or ai.chat.
    health_status_keys = (
        "系统检测",
        "打开系统检测",
        "系统状态",
        "系统状态怎么样",
        "检查系统状态",
        "健康检查",
    )
    short_keys = ("怎么处理", "建议是什么", "解决方案", "要不要")
    verbose_keys = ("为什么", "原因", "为何", "详细", "具体", "优先级", "开工单", "改哪个文件", "展开")
    abnormal_hit = any(k in q for k in ("哪些模块异常", "哪个模块异常", "异常模块", "模块异常"))
    priority_hit = any(k in q for k in ("优先处理", "优先关注", "先处理", "处理什么", "建议先"))
    disposition_hit = any(k in q for k in short_keys) or any(k in q for k in verbose_keys) or abnormal_hit or priority_hit
    module_status_hit = (
        any(k in q for k in ("模块", "健康", "状态"))
        and any(k in q for k in ("正常", "异常", "未知", "降级", "健康", "状态"))
    )
    if any(k in q for k in health_status_keys) or disposition_hit or module_status_hit:
        if priority_hit:
            intent = "priority"
        elif abnormal_hit or module_status_hit:
            intent = "abnormal"
        elif disposition_hit:
            intent = "module"
        else:
            intent = "summary"
        return {
            "route": "system.health_check",
            "source": "system.health_check",
            "short_circuit": True,
            "intent": intent,
            "verbose": any(k in q for k in verbose_keys),
        }

    return {
        "route": "ai.chat",
        "source": "ai.chat",
        "short_circuit": False,
        "intent": "chat",
    }


def _is_status_diagnostic_context(q: str) -> bool:
    keys = (
        "系统检测",
        "打开系统检测",
        "系统状态",
        "检查系统状态",
        "健康检查",
        "诊断运行态",
        "运行态诊断",
        "诊断信息",
        "调试信息",
        "运维诊断",
        "当前模型",
        "当前后端",
        "当前模型路径",
        "模型路径是什么",
        "后端是什么",
        "模型是什么",
        "后端状态",
        "模型状态",
        "base_url",
    )
    return any(k in q for k in keys)


def _exposes_internal_status(text: str) -> bool:
    keys = (
        "【运行态真相摘要】",
        "当前 base_url",
        "当前模型路径",
        "当前运行时模型名",
        "运行态探测",
        "配置值（运行态探测不可用）",
        "runtime_model_truth",
        "backend_status",
        "AICore",
        "MemoryManager",
    )
    return any(k in str(text or "") for k in keys)


def _status_boundary_reply() -> str:
    return "我先按普通对话处理，不主动展开内部运行态和调试链路信息。你可以继续说需求；如果需要状态诊断，请明确说“系统检测”或“诊断运行态”。"


class CapabilityEntrySummaryBuilder:
    """Builds user-facing capability entry summaries from visible action metadata."""

    def __init__(self, actions: Any):
        self.action_names = self._action_names(actions)

    @staticmethod
    def _action_names(actions: Any) -> list[str]:
        if isinstance(actions, dict):
            return sorted(str(k) for k in actions.keys() if str(k or "").strip())
        if not isinstance(actions, list):
            return []

        names = []
        for item in actions:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    names.append(name)
        return sorted(set(names))

    def build(self) -> str:
        parts = [
            "我可以作为本地数字中控助手帮你处理这些事：",
            "1. 对话与问答：解释项目、梳理上下文、回答你的日常问题。",
            "2. 系统检测：查看系统健康、模块状态、异常原因和处置建议。",
            "3. 记忆辅助：在可用记忆范围内回忆身份信息和最近对话。",
            "4. 本地能力转接：在已接入能力范围内帮你触发语音播报等本地动作。",
        ]
        if self.action_names:
            parts.append("当前系统已接入多项可用能力；你可以直接说需求，我会优先走稳定的本地能力链。")
        else:
            parts.append("当前没有拿到完整能力清单，但聊天和系统检测主链仍会按稳定入口兜底。")
        return "\n".join(parts)


def _build_system_health_summary(health: dict) -> str:
    modules = health.get("modules", {}) if isinstance(health, dict) else {}
    modules = modules if isinstance(modules, dict) else {}

    overall = health.get("health") or health.get("status") or "UNKNOWN"
    overall = str(overall or "UNKNOWN").strip().upper()

    buckets = _system_health_buckets(health)
    ok = buckets["ok"]
    warn = buckets["warn"]
    err = buckets["err"]
    stopped = buckets["stopped"]
    unk = buckets["unk"]

    usable, immediate, focus = _system_health_decision(buckets, has_modules=bool(modules))

    parts = [f"系统健康：{overall}"]
    if modules:
        parts.append(f"模块总数：{len(modules)}")
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
    if not modules:
        parts.append("当前没有拿到模块明细。")

    parts.extend([
        f"是否可正常使用：{usable}",
        f"是否建议立即处理：{immediate}",
        f"建议优先关注项：{focus}",
    ])
    return "\n".join(parts)


def _system_health_buckets(health: dict) -> dict[str, list[str]]:
    modules = health.get("modules", {}) if isinstance(health, dict) else {}
    modules = modules if isinstance(modules, dict) else {}
    ok, warn, err, stopped, unk = [], [], [], [], []
    for name, info in modules.items():
        if not isinstance(info, dict):
            unk.append(str(name))
            continue
        status = info.get("status") or info.get("health") or "UNKNOWN"
        status = str(status or "UNKNOWN").strip().upper()
        if status in ("OK", "READY"):
            ok.append(str(name))
        elif status == "STOPPED":
            stopped.append(str(name))
        elif status in ("WARNING", "DEGRADED"):
            warn.append(str(name))
        elif status in ("ERROR", "CRITICAL", "FAILED", "FAIL"):
            err.append(str(name))
        else:
            unk.append(str(name))
    return {"ok": ok, "warn": warn, "err": err, "stopped": stopped, "unk": unk}


def _system_health_decision(buckets: dict[str, list[str]], *, has_modules: bool) -> tuple[str, str, str]:
    err = buckets.get("err") or []
    warn = buckets.get("warn") or []
    stopped = buckets.get("stopped") or []
    unk = buckets.get("unk") or []
    if err:
        usable = "否，存在异常模块，建议先处理后再依赖相关能力。"
        immediate = "是，建议优先处理异常模块。"
        focus = "、".join(err)
    elif warn:
        usable = "基本可用，但存在警告/降级模块。"
        immediate = "否，可先继续使用；建议尽快检查警告/降级模块。"
        focus = "、".join(warn)
    elif stopped:
        usable = "部分可用，停止模块对应能力可能不可用。"
        immediate = "否，可暂缓；需要相关能力时再启动或排查停止模块。"
        focus = "、".join(stopped)
    elif unk or not has_modules:
        usable = "暂不确定，当前健康数据不完整。"
        immediate = "否，但建议补齐模块状态后再判断。"
        focus = "、".join(unk) if unk else "模块明细缺失"
    else:
        usable = "是，当前未发现异常或降级模块。"
        immediate = "否，当前无需立即处理。"
        focus = "暂无，保持观察即可。"
    return usable, immediate, focus


def _build_system_status_reply(
    health: dict,
    q: str,
    *,
    intent: str = "summary",
    verbose: bool = False,
) -> str:
    if not isinstance(health, dict):
        return str(health)

    summary = _build_system_health_summary(health)
    buckets = _system_health_buckets(health)
    modules = health.get("modules", {})
    modules = modules if isinstance(modules, dict) else {}

    if intent == "abnormal":
        abnormal = buckets["err"] + buckets["warn"] + buckets["stopped"] + buckets["unk"]
        line = "异常/需关注模块：" + ("、".join(abnormal) if abnormal else "暂无")
        return "\n\n".join([summary, line])

    if intent == "priority":
        _usable, immediate, focus = _system_health_decision(buckets, has_modules=bool(modules))
        line = "\n".join([
            f"优先处理建议：{focus}",
            f"是否建议立即处理：{immediate}",
        ])
        return "\n\n".join([summary, line])

    if intent != "module":
        return summary

    hits = [name for name in modules.keys() if name and name in q]
    blocks = []
    for hit in hits:
        info = modules.get(hit) or {}
        status = str(info.get("status") or info.get("health") or "UNKNOWN").strip().upper()
        reason = str(info.get("reason") or "").strip()
        detail = info.get("detail")
        block = _build_module_disposition(hit, status, reason, detail, verbose=verbose)
        if block:
            blocks.append(block)
    if not blocks:
        return summary
    return "\n\n".join([summary, *blocks])


def _build_sysmon_status_reply(status: Any) -> str:
    if isinstance(status, str):
        return status
    if not isinstance(status, dict):
        return str(status or "")

    if isinstance(status.get("reply"), str):
        return status["reply"]
    if isinstance(status.get("summary"), str):
        return status["summary"]
    if isinstance(status.get("status"), str):
        return f"系统监控状态：{status['status']}"
    return "系统监控状态：" + str(status)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _active_backend_entry(backend_status: Any) -> tuple[str, dict]:
    if not isinstance(backend_status, dict):
        return "", {}
    fallback = ("", {})
    for name, entry in backend_status.items():
        if not isinstance(entry, dict):
            continue
        if not fallback[1]:
            fallback = (str(name or "").strip(), entry)
        if entry.get("is_active"):
            return str(name or "").strip(), entry
    return fallback


def _runtime_truth_view(status: dict) -> dict:
    status = status if isinstance(status, dict) else {}
    truth = status.get("runtime_model_truth") or {}
    truth = truth if isinstance(truth, dict) else {}
    backend_status = status.get("backend_status") or {}
    backend_name, backend_entry = _active_backend_entry(backend_status)
    backend_entry = backend_entry if isinstance(backend_entry, dict) else {}
    config = backend_entry.get("config") or {}
    config = config if isinstance(config, dict) else {}
    backend_info = backend_entry.get("backend_info") or {}
    backend_info = backend_info if isinstance(backend_info, dict) else {}

    models = truth.get("models") if isinstance(truth.get("models"), list) else []
    runtime_model = _first_text(
        truth.get("runtime_model"),
        truth.get("model_name"),
        truth.get("model"),
        models[0] if models else "",
    )
    config_model = _first_text(config.get("model_name"), backend_info.get("model_name"))
    env_model_path = _first_text(os.getenv("SANHUA_MODEL"), os.getenv("SANHUA_MODEL_PATH"))
    env_model_name = _first_text(os.getenv("SANHUA_ACTIVE_MODEL"), os.getenv("SANHUA_MODEL_NAME"))
    model_name = runtime_model or config_model or env_model_name or os.path.basename(env_model_path)
    model_source = "运行态探测值" if runtime_model else "配置值（运行态探测不可用）"

    backend_type = _first_text(
        backend_info.get("type"),
        config.get("type"),
        os.getenv("SANHUA_BACKEND_TYPE"),
        os.getenv("SANHUA_LLM_BACKEND"),
        os.getenv("AICORE_LLM_BACKEND"),
    )
    backend_label = _first_text(backend_name, backend_type)
    backend_source = "运行态探测值" if backend_name or backend_info else "配置值（运行态探测不可用）"

    runtime_model_path = _first_text(truth.get("model_path"), truth.get("path"))
    model_path = _first_text(
        runtime_model_path,
        backend_info.get("model_path"),
        config.get("model_path"),
        env_model_path,
    )
    if not model_path and ("/" in config_model or config_model.endswith(".gguf")):
        model_path = config_model
    path_source = "运行态探测值" if _first_text(runtime_model_path, backend_info.get("model_path")) else "配置值（运行态探测不可用）"

    runtime_base_url = _first_text(
        truth.get("base_url"),
        truth.get("api_base"),
        truth.get("endpoint"),
    )
    base_url = _first_text(
        runtime_base_url,
        backend_info.get("base_url"),
        backend_info.get("api_base"),
        backend_info.get("endpoint"),
        config.get("base_url"),
        config.get("api_base"),
        config.get("endpoint"),
        os.getenv("SANHUA_LLAMA_BASE_URL"),
        os.getenv("OPENAI_BASE_URL"),
    )
    base_url_source = "运行态探测值" if _first_text(runtime_base_url, backend_info.get("base_url"), backend_info.get("api_base"), backend_info.get("endpoint")) else "配置值（运行态探测不可用）"
    probe_available = bool(truth or backend_status)

    return {
        "__runtime_truth_view__": True,
        "model_name": model_name,
        "model_source": model_source,
        "backend_label": backend_label,
        "backend_source": backend_source,
        "model_path": model_path,
        "path_source": path_source,
        "base_url": base_url,
        "base_url_source": base_url_source,
        "probe_available": probe_available,
    }


def _runtime_model_truth_reply(kind: str, status: dict) -> str:
    fields = _runtime_truth_view(status)

    model_name = fields["model_name"]
    model_source = fields["model_source"]
    backend_label = fields["backend_label"]
    backend_source = fields["backend_source"]
    model_path = fields["model_path"]
    path_source = fields["path_source"]

    if kind == "model":
        focus = f"模型名：{model_name or '未知'}（{model_source}）"
    elif kind == "backend":
        focus = f"后端名：{backend_label or '未知'}（{backend_source}）"
    else:
        focus = f"模型路径：{model_path or '未知'}（{path_source}）"

    return "\n".join([
        "当前运行态模型信息：",
        focus,
        f"模型名：{model_name or '未知'}（{model_source}）",
        f"后端名：{backend_label or '未知'}（{backend_source}）",
        f"模型路径：{model_path or '未知'}（{path_source}）",
    ])


def _build_runtime_truth_context(status: dict) -> str:
    fields = _runtime_truth_view(status)
    probe_text = "可用" if fields["probe_available"] else "不可用"
    parts = [
        "【运行态真相摘要】",
        f"- 运行态探测：{probe_text}",
        f"- 当前后端名：{fields['backend_label'] or '未知'}（{fields['backend_source']}）",
        f"- 当前运行时模型名：{fields['model_name'] or '未知'}（{fields['model_source']}）",
        f"- 当前模型路径：{fields['model_path'] or '未知'}（{fields['path_source']}）",
        f"- 当前 base_url：{fields['base_url'] or '未知'}（{fields['base_url_source']}）",
    ]
    if any("配置值" in fields[key] for key in ("model_source", "backend_source", "path_source", "base_url_source")):
        parts.append("- 降级说明：标注为配置值的字段表示运行态探测缺失或不完整，当前使用配置/env 兜底。")
    return "\n".join(parts)


class AIChatContextBuilder:
    """Builds ai.chat payloads from user input, memory truth, and runtime truth."""

    def __init__(
        self,
        aicore: Any,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.aicore = aicore
        self.logger = logger

    def _log(self, text: str) -> None:
        if callable(self.logger):
            try:
                self.logger(text)
                return
            except Exception:
                pass
        print(text)

    def _build_memory_truth_prompt(self, user_text: str, system_prompt: str) -> str:
        ac = self.aicore
        prompt = user_text

        if ac is not None:
            payload_builder = getattr(ac, "build_memory_payload", None)
            if callable(payload_builder):
                try:
                    payload = payload_builder(user_text, system_persona=system_prompt)
                    if isinstance(payload, dict):
                        for key in ("final_prompt", "prompt", "text", "message"):
                            value = payload.get(key)
                            if isinstance(value, str) and value.strip():
                                prompt = value
                                break
                except Exception as e:
                    self._log(f"⚠️ build_memory_payload 失败，回退原始输入: {e}")

            if prompt == user_text:
                prompt_builder = getattr(ac, "build_memory_prompt", None)
                if callable(prompt_builder):
                    try:
                        memory_prompt = prompt_builder(user_text, system_persona=system_prompt)
                        if isinstance(memory_prompt, str) and memory_prompt.strip():
                            prompt = memory_prompt
                    except Exception as e:
                        self._log(f"⚠️ build_memory_prompt 失败，回退原始输入: {e}")

        return prompt

    def _get_runtime_status_for_context(self) -> dict:
        ac = self.aicore
        try:
            get_status = getattr(ac, "get_status", None)
            status = get_status() if callable(get_status) else {}
        except Exception as e:
            self._log(f"⚠️ AICore.get_status 失败，ai.chat 使用配置/env 运行态上下文降级: {e}")
            status = {}
        return status if isinstance(status, dict) else {}

    def _build_ai_chat_prompt(self, user_text: str, system_prompt: str) -> str:
        prompt = self._build_memory_truth_prompt(user_text, system_prompt)
        status = self._get_runtime_status_for_context()
        return "\n\n".join([prompt, _build_runtime_truth_context(status)])

    def build(self, user_text: str, system_prompt: str) -> dict[str, str]:
        prompt = self._build_ai_chat_prompt(user_text, system_prompt)
        return {
            "query": user_text,
            "prompt": prompt,
            "message": prompt,
            "text": prompt,
            "system_prompt": system_prompt,
            "system": system_prompt,
        }


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
        self.ai_chat_context_builder = AIChatContextBuilder(
            aicore=self.aicore,
            logger=self._log,
        )

    def _log(self, text: str) -> None:
        if callable(self.logger):
            try:
                self.logger(text)
                return
            except Exception:
                pass
        print(text)

    def _trace(
        self,
        *,
        route: str,
        source: str,
        short_circuit: bool,
        display_boundary: bool = False,
        writeback: str = "none",
    ) -> None:
        self._log(
            "TRACE chat "
            f"route={route} "
            f"source={source} "
            f"short_circuit={str(short_circuit).lower()} "
            f"display_boundary={str(display_boundary).lower()} "
            f"writeback={writeback}"
        )

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
            self._trace(route="local_memory", source="memory.local", short_circuit=True, writeback="local_memory")
            return local_reply

        # 0.5) 模块原因/处置问答短路（短答/展开）
        q = user_text.replace("？", "?").replace("。", "").strip()
        route_decision = _classify_chat_route(q)

        if route_decision["route"] == "sysmon.status":
            try:
                self._log("🧭 chat short-circuit -> sysmon.status")
                status = self.action_caller("sysmon.status", {})
                reply = _build_sysmon_status_reply(status).strip()
                if reply:
                    self._trace(route="sysmon.status", source="sysmon.status", short_circuit=True)
                    return reply
            except Exception as e:
                self._log(f"⚠️ sysmon.status 短路失败: {e}")
            self._trace(route="sysmon.status.unavailable", source="sysmon.status.unavailable", short_circuit=True)
            return "系统监控状态暂不可用：当前未拿到 sysmon.status 的有效结果。"

        if route_decision["route"] == "system.health_check":
            try:
                self._log("🧭 chat short-circuit -> system.health_check [sys_detect]")
                health = self.action_caller("system.health_check", {})
                if isinstance(health, str):
                    self._trace(route="system.health_check", source="system.health_check", short_circuit=True)
                    return health
                if isinstance(health, dict):
                    reply = _build_system_status_reply(
                        health,
                        q,
                        intent=route_decision.get("intent", "summary"),
                        verbose=bool(route_decision.get("verbose")),
                    )
                    if reply:
                        self._trace(route="system.health_check", source="system.health_check", short_circuit=True)
                        return reply
                self._trace(route="system.health_check", source="system.health_check", short_circuit=True)
                return str(health)
            except Exception as e:
                self._log(f"⚠️ system.health_check 短路失败: {e}")

        # 0.7) 助手身份/能力类确定性短路
        if _is_assistant_identity_question(q):
            self._log("🧭 chat short-circuit -> assistant.identity")
            self._trace(route="assistant.identity", source="deterministic_rule", short_circuit=True)
            return "我是三花聚顶·聚核助手，本地数字中控助手。我的职责是帮你对话、查看系统状态，并在已注册动作范围内转接本地能力。"

        if _is_capability_question(q):
            self._log("🧭 chat short-circuit -> system.capabilities")
            try:
                actions = self.list_actions()
            except Exception:
                actions = []
            self._trace(route="system.capabilities", source="list_actions", short_circuit=True)
            return CapabilityEntrySummaryBuilder(actions).build()

        if route_decision["route"] == "runtime.model_truth":
            self._log("🧭 chat short-circuit -> runtime.model_truth")
            try:
                get_status = getattr(self.aicore, "get_status", None)
                status = get_status() if callable(get_status) else {}
            except Exception as e:
                self._log(f"⚠️ AICore.get_status 失败，改用配置/env 降级: {e}")
                status = {}
            self._trace(route="runtime.model_truth", source="aicore.get_status", short_circuit=True)
            return _runtime_model_truth_reply(route_decision.get("intent", ""), status)

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
            ai_context = self.ai_chat_context_builder.build(user_text, system_prompt)
            ai_prompt = ai_context["prompt"]
            res = self.action_caller("ai.chat", ai_context)
            reply = self._extract_reply(res)
            if reply:
                if display_is_polluted(reply):
                    self._log("🧼 GUI display sanitize -> polluted ai.chat reply blocked")
                    local_reply = self._try_local_memory(user_text)
                    if local_reply:
                        self._trace(route="ai.chat.polluted_local_memory", source="ai.chat", short_circuit=False, writeback="local_memory")
                        return local_reply
                else:
                    display_boundary = False
                    if not _is_status_diagnostic_context(q) and _exposes_internal_status(reply):
                        self._log("🧼 GUI display boundary -> internal status hidden for normal chat")
                        reply = _status_boundary_reply()
                        display_boundary = True
                    sanitized = sanitize_reply_for_writeback(user_text, ai_prompt, reply)
                    if sanitized:
                        append_chat(self.aicore, "user", user_text)
                        append_chat(self.aicore, "assistant", sanitized)
                        append_action(self.aicore, "ai.chat", "success", sanitized[:200])
                    self._trace(
                        route="ai.chat",
                        source="ai.chat",
                        short_circuit=False,
                        display_boundary=display_boundary,
                        writeback="sanitize_reply_for_writeback" if sanitized else "sanitize_empty",
                    )
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
                                self._trace(route="AICore.chat.polluted_local_memory", source="AICore.chat", short_circuit=False, writeback="local_memory")
                                return local_reply
                        else:
                            self._trace(route="AICore.chat", source="AICore.chat", short_circuit=False)
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
                            self._trace(route="action:aicore.chat.polluted_local_memory", source="action:aicore.chat", short_circuit=False, writeback="local_memory")
                            return local_reply
                    else:
                        self._trace(route="action:aicore.chat", source="action:aicore.chat", short_circuit=False)
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
                                self._trace(route="AICore.ask.polluted_local_memory", source="AICore.ask", short_circuit=False, writeback="local_memory")
                                return local_reply
                        else:
                            self._trace(route="AICore.ask", source="AICore.ask", short_circuit=False)
                            return reply
        except RecursionError:
            self._log("❌ AICore.ask 失败: recursion detected")
        except Exception as e:
            self._log(f"❌ AICore.ask 失败: {e}")

        # 5) 最后再试一次本地记忆兜底
        local_reply = self._try_local_memory(user_text)
        if local_reply:
            self._trace(route="local_memory.final_fallback", source="memory.local", short_circuit=False, writeback="local_memory")
            return local_reply

        return "抱歉，我这次没有拿到有效回复。"
