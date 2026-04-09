#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import json
import time
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aicore_doctor")


def _now() -> float:
    return time.time()


def _ok(name: str, detail: Any = None) -> Dict[str, Any]:
    return {"name": name, "status": "OK", "detail": detail}


def _warn(name: str, detail: Any = None) -> Dict[str, Any]:
    return {"name": name, "status": "WARN", "detail": detail}


def _fail(name: str, detail: Any = None) -> Dict[str, Any]:
    return {"name": name, "status": "FAIL", "detail": detail}


def _skip(name: str, detail: Any = None) -> Dict[str, Any]:
    return {"name": name, "status": "SKIP", "detail": detail}


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return repr(x)


def _import_check() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    must = ["requests", "yaml"]
    for m in must:
        try:
            __import__(m)
            checks.append(_ok(f"import:{m}"))
        except Exception as e:
            checks.append(_fail(f"import:{m}", _safe_str(e)))
    return checks


def _load_config() -> Tuple[Optional[Any], Dict[str, Any]]:
    try:
        from core.aicore.config import AICoreConfig
        cfg = AICoreConfig.from_env()
        active = cfg.get_active_backends()
        detail = {
            "identity": getattr(cfg, "identity", {}),
            "active_backends": [b.to_dict() for b in active],
        }
        if not active:
            return cfg, _fail("config.active_backends", "get_active_backends() 为空")
        return cfg, _ok("config.load", detail)
    except Exception as e:
        return None, _fail("config.load", _safe_str(e))


def _init_aicore(cfg: Any) -> Tuple[Optional[Any], Dict[str, Any]]:
    try:
        from core.aicore import ExtensibleAICore
        ac = ExtensibleAICore(cfg)
        return ac, _ok("aicore.init", {"version": getattr(ac, "VERSION", "unknown")})
    except Exception as e:
        return None, _fail("aicore.init", _safe_str(e))


def _check_backends(ac: Any) -> Dict[str, Any]:
    try:
        status = ac.backend_manager.get_backend_status()
        if not status:
            return _fail("backend.status", "backend_manager.get_backend_status() 为空")

        # 每个后端健康检查（如果后端实现提供）
        per = {}
        for name, st in status.items():
            per[name] = {
                "is_active": st.get("is_active"),
                "healthy": st.get("healthy"),
                "type": st.get("config", {}).get("type"),
                "base_url": st.get("config", {}).get("base_url"),
            }

        # 至少一个可用
        healthy_any = any(v.get("healthy") is True for v in per.values())
        if not healthy_any:
            return _warn("backend.health", {"note": "没有后端返回 healthy=True（可能是 health_check 不支持）", "backends": per})

        return _ok("backend.health", per)
    except Exception as e:
        return _fail("backend.health", _safe_str(e))


def _check_logs(ac: Any) -> Dict[str, Any]:
    """
    规则：
    - 如果能拿到日志 tail：OK
    - 拿不到：WARN（因为纯 llama-server 通常没有 /logs）
    """
    try:
        if not hasattr(ac, "controller"):
            return _warn("observability.logs", "aicore.controller 不存在（未挂载 compat controller）")

        logs = ac.controller.recent_logs("stderr", 30)
        if logs:
            return _ok("observability.logs", {"lines": logs[-10:]})
        return _warn(
            "observability.logs",
            "未获取到日志（如果你连接的是纯 llama-server:8080 这是正常的；如果你期望走 manager，应把 base_url 指向 manager 端口如 9000）"
        )
    except Exception as e:
        return _warn("observability.logs", _safe_str(e))


def _ensure_actions_registered(ac: Any) -> Dict[str, Any]:
    """
    目标：保证 ACTION_MANAGER 内至少有 show_time/show_date 等“安全动作”
    说明：只做注册，不执行高风险 OS 动作
    """
    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        # 如果动作已存在，直接 OK
        if ACTION_MANAGER.get_action("show_time") and ACTION_MANAGER.get_action("show_date"):
            return _ok("actions.registered", "核心动作已存在（show_time/show_date）")

        # 否则尝试通过 ActionMapper 注册（只注册，不调用）
        from core.aicore.action_manager import ActionMapper
        _ = ActionMapper(ac)  # 构造函数会 register_all_actions()
        ok = bool(ACTION_MANAGER.get_action("show_time")) and bool(ACTION_MANAGER.get_action("show_date"))
        if ok:
            return _ok("actions.registered", "已通过 ActionMapper 注册动作（show_time/show_date）")
        return _warn("actions.registered", "ActionMapper 已执行但 show_time/show_date 仍不存在（检查 ActionMapper.register_all_actions）")
    except Exception as e:
        return _fail("actions.registered", _safe_str(e))


def _intent_plan_action_smoke(ac: Any) -> Dict[str, Any]:
    """
    验证：IntentRecognizer -> ActionSynthesizer -> ACTION_MANAGER.execute
    - 自动跳过高风险/需确认动作
    """
    try:
        from core.core2_0.sanhuatongyu.action_dispatcher import ACTION_MANAGER
        from core.aicore.intent_action_generator.intent_recognizer import IntentRecognizer
        from core.aicore.intent_action_generator.action_synthesizer import ActionSynthesizer

        ir = IntentRecognizer()
        planner = ActionSynthesizer(registry=None)

        tests = [
            ("显示当前日期", "show_date"),
            ("现在时间", "show_time"),
            ("打开浏览器", "open_browser"),
            ("打开网址:https://www.bing.com", "open_url"),
            ("锁屏", "lock_screen"),  # 中风险/可能平台不支持，这里允许但可被 need_confirm 标记
            ("关机", "shutdown"),      # 高风险：必须跳过
        ]

        results: List[Dict[str, Any]] = []

        for text, expected in tests:
            item: Dict[str, Any] = {"query": text, "expected_action": expected}

            intent_obj = ir.recognize(text)
            item["intent_obj"] = {k: intent_obj.get(k) for k in ("type", "intent", "action_name", "risk", "need_confirm", "confidence")}

            if intent_obj.get("type") != "intent":
                item["status"] = "FAIL"
                item["reason"] = "intent_not_matched"
                results.append(item)
                continue

            plan = planner.synthesize(intent_obj)
            if not plan:
                item["status"] = "FAIL"
                item["reason"] = "plan_none"
                results.append(item)
                continue

            item["plan"] = plan.to_dict()
            action = plan.action

            # 风险治理：高风险/需确认直接跳过
            if plan.need_confirm or plan.risk in ("high",):
                item["status"] = "SKIP"
                item["reason"] = f"risk={plan.risk}, need_confirm={plan.need_confirm}"
                results.append(item)
                continue

            # 动作必须存在
            if not ACTION_MANAGER.get_action(action):
                item["status"] = "FAIL"
                item["reason"] = f"action_not_registered:{action}"
                results.append(item)
                continue

            # 执行（注意：某些动作依赖系统命令，可能失败，但这仍然是“链路通了”）
            try:
                out = ACTION_MANAGER.execute(action, query=text, params=plan.params or {})
                item["status"] = "OK"
                item["action_result"] = out
            except Exception as e:
                item["status"] = "WARN"
                item["reason"] = f"execute_error:{_safe_str(e)}"

            results.append(item)

        # 统计
        ok_n = sum(1 for r in results if r["status"] == "OK")
        fail_n = sum(1 for r in results if r["status"] == "FAIL")
        return _ok("intent.plan.action", {"ok": ok_n, "fail": fail_n, "details": results})
    except Exception as e:
        return _fail("intent.plan.action", _safe_str(e))


def _system_state_context_smoke() -> Dict[str, Any]:
    """
    验证：SystemState & LlamaContext 能构造并注入系统状态文本
    """
    try:
        from core.aicore.system_state import SystemState
        from core.aicore.llama_context import LlamaContext

        ss = SystemState()
        ss.update()
        st = ss.get_state()

        ctx = LlamaContext(max_tokens=512)
        # 某些实现里 LlamaContext 可能自己 new SystemState；这里确保可调用
        if hasattr(ctx, "update_system_state"):
            ctx.update_system_state()
        text = ctx.get_context() if hasattr(ctx, "get_context") else ""

        return _ok("system.context", {
            "system_state_keys": list(st.keys()),
            "context_has_system_state": ("System State" in text) or ("cpu_usage" in text) or ("memory_usage" in text),
        })
    except Exception as e:
        return _warn("system.context", _safe_str(e))


def main() -> int:
    report: Dict[str, Any] = {
        "ts": _now(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
        },
        "checks": [],
    }

    report["checks"].extend(_import_check())

    cfg, cfg_check = _load_config()
    report["checks"].append(cfg_check)
    if cfg is None or cfg_check["status"] == "FAIL":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    ac, ac_check = _init_aicore(cfg)
    report["checks"].append(ac_check)
    if ac is None or ac_check["status"] == "FAIL":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    report["checks"].append(_check_backends(ac))
    report["checks"].append(_check_logs(ac))

    # 关键：动作链路需要 ACTION_MANAGER 有动作
    report["checks"].append(_ensure_actions_registered(ac))
    report["checks"].append(_intent_plan_action_smoke(ac))

    # 系统感知（SystemState/LlamaContext）
    report["checks"].append(_system_state_context_smoke())

    # 结论
    status_rank = {"OK": 0, "SKIP": 1, "WARN": 2, "FAIL": 3}
    worst = "OK"
    for c in report["checks"]:
        if status_rank.get(c["status"], 99) > status_rank.get(worst, 99):
            worst = c["status"]
    report["result"] = worst

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if worst in ("OK", "SKIP") else 1


if __name__ == "__main__":
    raise SystemExit(main())
