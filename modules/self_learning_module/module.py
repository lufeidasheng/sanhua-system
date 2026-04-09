#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三花聚顶 · self_learning（企业版 v2.3）
作用：运行期自学习与自适应调优（响应延迟/优先级因子/重试次数）
特性：BaseModule标准 · Fedora优化 · 线程安全 · 滑动窗口 · 健康检查 · 事件总线 · 指标采集 · 状态持久化
"""

from __future__ import annotations
import os, sys, json, time, asyncio, threading
from collections import deque
from typing import Dict, Optional, List, Any

# --- 可选依赖（安全降级） ---
try:
    import psutil  # type: ignore
    _HAVE_PSUTIL = True
except Exception:
    psutil = None
    _HAVE_PSUTIL = False

# ==== 三花聚顶基座 ====
from core.core2_0.sanhuatongyu.module.base import BaseModule
from core.core2_0.sanhuatongyu.logger import get_logger
from core.core2_0.sanhuatongyu.action_dispatcher import dispatcher as ACTIONS

log = get_logger("self_learning")

# ==== 环境探测 ====
IS_FEDORA = os.path.exists("/etc/fedora-release")

# ==== 元信息（供主控读取）====
__metadata__ = {
    "id": "self_learning",
    "name": "自学习模块",
    "version": "2.3",
    "dependencies": ["psutil"] if _HAVE_PSUTIL else [],
    "entry_class": "modules.self_learning.module.SelfLearningModule",
    "events": [
        "task.completed",        # {task_name, success, response_time}
        "system.feedback",       # {type: user_rating/error_report, ...}
        "perf.alert",            # {alert_type: high_cpu/... , metric: {}}
        "learning.query",
        "learning.reset",
        "learning.update_config",
    ],
}

# ===== 内核实现 =====
class SelfLearningCore:
    def __init__(self, initial_config: Optional[Dict] = None):
        # 锁：Fedora 用 RLock（多重进入更安全）
        self._lock = threading.RLock() if IS_FEDORA else threading.Lock()

        # 内核参数（运行时动态调整）
        fedora_defaults = {
            "response_delay": 0.3 if IS_FEDORA else 0.5,
            "priority_factor": 1.2 if IS_FEDORA else 1.0,
            "retry_limit": 4 if IS_FEDORA else 3,
        }
        self.kernel_params: Dict[str, Any] = fedora_defaults.copy()

        # 学习配置（阈值、滑窗、步长等）
        self.learning_config: Dict[str, Any] = {
            "response_time_threshold": 1.0,
            "adjustment_step": 0.05,
            "success_rate_target": 0.95,
            "history_size": 1000,
            "window_size": 100,
            "min_adjust_interval": 15,
        }
        if IS_FEDORA:
            self.learning_config.update({
                "response_time_threshold": 0.8,
                "adjustment_step": 0.03,
                "success_rate_target": 0.97,
                "history_size": 1500,
                "window_size": 150,
                "min_adjust_interval": 10,
            })

        if initial_config:
            self.update_config(initial_config)

        # 全局统计
        self.task_stats = {
            "total_tasks": 0,
            "success_tasks": 0,
            "fail_tasks": 0,
            "avg_response_time": 0.0,
            "success_rate": 0.0,
        }

        # 高效滑窗
        self.window_stats: deque = deque(maxlen=self.learning_config["window_size"])
        self.window_sum = 0.0
        self.window_successes = 0

        # 任务历史
        self.task_history: deque = deque(maxlen=self.learning_config["history_size"])

        # 学习状态
        self.learning_state = {
            "last_adjustment": 0.0,
            "adjustment_count": 0,
            "last_trigger": None,
            "last_perf_check": 0.0,
        }

        # 性能指标
        self.performance = {
            "event_processing_time": 0.0,
            "event_count": 0,
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
        }
        if IS_FEDORA:
            self.performance.update({"disk_io": 0.0, "network_io": 0.0})

    # -------- 内部工具 --------
    def _update_perf(self):
        if not _HAVE_PSUTIL:
            return
        try:
            self.performance["cpu_usage"] = psutil.cpu_percent(interval=0.05)  # 快速采样
            self.performance["memory_usage"] = psutil.virtual_memory().percent
            if IS_FEDORA:
                disk_io = psutil.disk_io_counters()
                net_io = psutil.net_io_counters()
                self.performance["disk_io"] = (disk_io.read_bytes + disk_io.write_bytes)
                self.performance["network_io"] = (net_io.bytes_sent + net_io.bytes_recv)
        except Exception as e:
            log.debug(f"[self_learning] 更新性能指标失败: {e}")

    # -------- 对外：统计更新 --------
    def update_task_stats(self, success: bool, response_time: float, task_type: str = "default"):
        with self._lock:
            now = time.time()

            # 1) 轻量性能采样（<= 1Hz）
            if now - self.learning_state.get("last_perf_check", 0) > 1:
                self._update_perf()
                self.learning_state["last_perf_check"] = now

            # 2) 全局统计
            self.task_stats["total_tasks"] += 1
            if success:
                self.task_stats["success_tasks"] += 1
            else:
                self.task_stats["fail_tasks"] += 1

            n = self.task_stats["total_tasks"]
            old_avg = self.task_stats["avg_response_time"]
            self.task_stats["avg_response_time"] = (old_avg * (n - 1) + response_time) / max(n, 1)
            self.task_stats["success_rate"] = (self.task_stats["success_tasks"] / n) if n else 0.0

            # 3) 滑窗维护
            if len(self.window_stats) >= self.window_stats.maxlen:  # type: ignore
                o_success, o_rt, _ = self.window_stats.popleft()
                self.window_sum -= o_rt
                if o_success:
                    self.window_successes -= 1

            self.window_stats.append((success, response_time, task_type))
            self.window_sum += response_time
            if success:
                self.window_successes += 1

            # 4) 历史写入
            self.task_history.append({
                "timestamp": now,
                "success": success,
                "response_time": response_time,
                "task_type": task_type,
                "cpu": self.performance.get("cpu_usage", 0.0),
            })

    # -------- 对外：参数调整 --------
    def adjust_parameters(self) -> bool:
        with self._lock:
            now = time.time()
            if now - self.learning_state["last_adjustment"] < self.learning_config["min_adjust_interval"]:
                return False
            wsize = len(self.window_stats)
            if wsize < 10:
                return False

            wavg = self.window_sum / wsize
            wrate = (self.window_successes / wsize) if wsize else 0.0

            adjusted = False
            step = self.learning_config["adjustment_step"]

            # 1) 响应时间过长 → 减少延迟
            if wavg > self.learning_config["response_time_threshold"]:
                old = self.kernel_params["response_delay"]
                factor = 1.5 if IS_FEDORA else 1.0
                newv = max(0.1, old - step * factor)
                if newv != old:
                    self.kernel_params["response_delay"] = newv
                    adjusted = True
                    log.info(f"[self_learning] 响应延迟: {old:.3f} → {newv:.3f}")

            # 2) 成功率不足 → 提升优先级因子
            if wrate < self.learning_config["success_rate_target"]:
                old = self.kernel_params["priority_factor"]
                factor = 1.2 if IS_FEDORA else 1.0
                newv = min(2.5, old + step * factor)
                if newv != old:
                    self.kernel_params["priority_factor"] = newv
                    adjusted = True
                    log.info(f"[self_learning] 优先级因子: {old:.3f} → {newv:.3f}")
            # 3) 成功率过高 → 适度回落优先级因子
            elif wrate > self.learning_config["success_rate_target"] + 0.05:
                old = self.kernel_params["priority_factor"]
                newv = max(0.5, old - step / 2)
                if newv != old:
                    self.kernel_params["priority_factor"] = newv
                    adjusted = True
                    log.info(f"[self_learning] 优先级因子(降): {old:.3f} → {newv:.3f}")

            if adjusted:
                self.learning_state["last_adjustment"] = now
                self.learning_state["adjustment_count"] += 1
                self.learning_state["last_trigger"] = "window"
            return adjusted

    # -------- 查询/历史/配置 --------
    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            wsize = len(self.window_stats)
            wavg = (self.window_sum / wsize) if wsize else 0.0
            wrate = (self.window_successes / wsize) if wsize else 0.0
            status = {
                "global_stats": self.task_stats.copy(),
                "window_stats": {"size": wsize, "avg_response_time": wavg, "success_rate": wrate},
                "kernel_params": self.kernel_params.copy(),
                "learning_state": self.learning_state.copy(),
                "performance": self.performance.copy(),
                "task_history_count": len(self.task_history),
                "system": {"os": "Fedora" if IS_FEDORA else "Linux", "fedora_optimized": IS_FEDORA},
            }
            if IS_FEDORA and _HAVE_PSUTIL:
                try:
                    status["performance"].update({
                        "load_avg": os.getloadavg()[0],
                        "disk_usage": psutil.disk_usage('/').percent,
                    })
                except Exception:
                    pass
            return status

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.task_history)[-limit:]

    def reset(self):
        with self._lock:
            self.task_stats.update({
                "total_tasks": 0,
                "success_tasks": 0,
                "fail_tasks": 0,
                "avg_response_time": 0.0,
                "success_rate": 0.0,
            })
            self.window_stats.clear()
            self.window_sum = 0.0
            self.window_successes = 0
            self.task_history.clear()
            self.learning_state.update({
                "last_adjustment": time.time(),
                "adjustment_count": 0,
                "last_trigger": None,
                "last_perf_check": 0.0,
            })
            log.info("[self_learning] 学习状态已重置")

    def update_config(self, new_cfg: Dict[str, Any]):
        with self._lock:
            for k, v in (new_cfg or {}).items():
                if k not in self.learning_config:
                    log.debug(f"[self_learning] 忽略未知配置项: {k}")
                    continue

                # 校验
                if k in ("response_time_threshold", "adjustment_step"):
                    if not isinstance(v, (int, float)) or v <= 0:
                        log.warning(f"[self_learning] 无效 {k}={v}")
                        continue
                elif k == "success_rate_target":
                    if not isinstance(v, (int, float)) or not (0 <= v <= 1):
                        log.warning(f"[self_learning] 无效 {k}={v}")
                        continue
                elif k in ("history_size", "window_size", "min_adjust_interval"):
                    if not isinstance(v, int) or v <= 0:
                        log.warning(f"[self_learning] 无效 {k}={v}")
                        continue

                # 应用
                if k == "window_size":
                    new_deque = deque(maxlen=v)
                    for item in list(self.window_stats)[-v:]:
                        new_deque.append(item)
                    self.window_stats = new_deque
                    self.window_sum = sum(rt for _, rt, _ in self.window_stats)
                    self.window_successes = sum(1 for s, _, _ in self.window_stats if s)
                    self.learning_config[k] = v
                    log.info(f"[self_learning] 窗口大小 → {v}")
                elif k == "history_size":
                    new_hist = deque(maxlen=v)
                    for item in list(self.task_history)[-v:]:
                        new_hist.append(item)
                    self.task_history = new_hist
                    self.learning_config[k] = v
                    log.info(f"[self_learning] 历史容量 → {v}")
                else:
                    self.learning_config[k] = v
                    log.info(f"[self_learning] 配置 {k} → {v}")

# 单例核心
CORE = SelfLearningCore()

# ===== BaseModule 封装 =====
class SelfLearningModule(BaseModule):
    VERSION = "2.3"

    def __init__(self, meta=None, context=None):
        super().__init__(meta, context)
        self._registered = False
        log.info(f"[self_learning] 初始化完成 v{self.VERSION} · Fedora={IS_FEDORA}")

    # 生命周期
    def preload(self):
        self._register_actions()
        # 订阅事件
        bus = getattr(self.context, "event_bus", None)
        if bus:
            for ev in ("task.completed", "system.feedback", "perf.alert",
                       "learning.query", "learning.reset", "learning.update_config"):
                bus.subscribe(ev, self.handle_event)
        log.info("[self_learning] preload 完成")

    def setup(self):
        # 可在此加载持久化状态
        try:
            path = os.path.join(os.path.dirname(__file__), "learning_state.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                # 只恢复必要只读信息，不直接覆盖内部结构
                log.info("[self_learning] 检测到历史状态，可按需接入恢复逻辑")
        except Exception as e:
            log.debug(f"[self_learning] 读取历史状态失败: {e}")
        log.info("[self_learning] setup 完成")

    def start(self):
        log.info("[self_learning] 启动完成")

    def stop(self):
        # 持久化
        try:
            path = os.path.join(os.path.dirname(__file__), "learning_state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(CORE.get_status(), f, ensure_ascii=False, indent=2)
            log.info("[self_learning] 学习状态已保存")
        except Exception as e:
            log.warning(f"[self_learning] 保存状态失败: {e}")
        log.info("[self_learning] 停止完成")

    def cleanup(self):
        log.info("[self_learning] cleanup 完成")

    def health_check(self) -> Dict[str, Any]:
        st = CORE.get_status()
        # 简单健康判断：窗口/成功率/事件耗时
        health = "正常"
        if st["global_stats"]["total_tasks"] > 50 and st["global_stats"]["success_rate"] < 0.7:
            health = "降级"
        if st["performance"]["event_processing_time"] > 0.5:
            health = "警告"
        return {
            "status": health,
            "module": getattr(self.meta, "name", "self_learning"),
            "version": self.VERSION,
            "stats": st["global_stats"],
            "window": st["window_stats"],
            "perf": st["performance"],
            "timestamp": time.time(),
        }

    # 事件入口
    def handle_event(self, event, *args, **kwargs):
        try:
            if hasattr(event, "name"):
                name, data = getattr(event, "name", ""), getattr(event, "data", {}) or {}
            elif isinstance(event, dict):
                name, data = event.get("name", ""), event.get("data", {}) or {}
            else:
                name, data = str(event or ""), kwargs.get("data", {}) or {}

            if name == "task.completed":
                # data: {task_name, success, response_time}
                CORE.update_task_stats(bool(data.get("success", False)),
                                       float(data.get("response_time", 0.5)),
                                       str(data.get("task_name", "default")))
                # CPU低时及时调整
                cpu = CORE.performance.get("cpu_usage", 0.0)
                if cpu < 70:
                    CORE.adjust_parameters()
                return {"status": "ok"}

            if name == "system.feedback":
                t = data.get("type", "generic")
                if t == "user_rating":
                    rating = int(data.get("rating", 3))
                    with CORE._lock:
                        old = CORE.kernel_params["priority_factor"]
                        step = 0.15 if IS_FEDORA else 0.1
                        if rating >= 4:
                            CORE.kernel_params["priority_factor"] = min(2.5, old + step)
                        elif rating <= 2:
                            CORE.kernel_params["priority_factor"] = max(0.5, old - step)
                        log.info(f"[self_learning] 用户评分调整优先级: {old:.3f} → {CORE.kernel_params['priority_factor']:.3f}")
                elif t == "error_report":
                    cnt = int(data.get("error_count", 1))
                    with CORE._lock:
                        old = CORE.kernel_params["retry_limit"]
                        CORE.kernel_params["retry_limit"] = min(7 if IS_FEDORA else 5, max(1, old + cnt))
                        log.info(f"[self_learning] 重试限制: {old} → {CORE.kernel_params['retry_limit']}")
                return {"status": "ok"}

            if name == "perf.alert":
                # data: {alert_type, metric:{}}
                if data.get("alert_type") == "high_cpu":
                    with CORE._lock:
                        old = CORE.kernel_params["response_delay"]
                        inc = 0.15 if IS_FEDORA else 0.2
                        CORE.kernel_params["response_delay"] = max(0.1, old * (1 + inc))  # 拉长延迟
                        log.info(f"[self_learning] 高CPU → 响应延迟: {old:.3f} → {CORE.kernel_params['response_delay']:.3f}")
                return {"status": "ok"}

            if name == "learning.query":
                return CORE.get_status()

            if name == "learning.reset":
                CORE.reset()
                return {"status": "success"}

            if name == "learning.update_config":
                CORE.update_config(data or {})
                return {"status": "success", "config": CORE.learning_config}

            log.debug(f"[self_learning] 忽略事件: {name}")
            return None
        except Exception as e:
            log.error(f"[self_learning] handle_event 异常: {e}")
            return {"error": str(e)}

    # ===== 动作实现 =====
    def action_learning_query(self, context=None, params=None, **kwargs):
        return CORE.get_status()

    def action_learning_reset(self, context=None, params=None, **kwargs):
        CORE.reset()
        return {"status": "success"}

    def action_learning_update(self, context=None, params=None, **kwargs):
        CORE.update_config((params or {}).get("config", {}))
        return {"status": "success", "config": CORE.learning_config}

    def action_learning_history(self, context=None, params=None, **kwargs):
        limit = int((params or {}).get("limit", 20))
        return CORE.get_history(limit)

    def action_learning_params(self, context=None, params=None, **kwargs):
        with CORE._lock:
            return CORE.kernel_params.copy()

    # 注册动作
    def _register_actions(self):
        if self._registered:
            return
        ACTIONS.register_action(
            name="learning.query", func=self.action_learning_query,
            description="查询自学习状态", permission="user", module="self_learning"
        )
        ACTIONS.register_action(
            name="learning.reset", func=self.action_learning_reset,
            description="重置自学习状态", permission="admin", module="self_learning"
        )
        ACTIONS.register_action(
            name="learning.update_config", func=self.action_learning_update,
            description="更新自学习配置", permission="admin", module="self_learning"
        )
        ACTIONS.register_action(
            name="learning.history", func=self.action_learning_history,
            description="获取近期任务历史", permission="user", module="self_learning"
        )
        ACTIONS.register_action(
            name="learning.params", func=self.action_learning_params,
            description="获取当前内核参数", permission="user", module="self_learning"
        )
        # 兼容中文 alias（可选）
        ACTIONS.register_action("查询学习状态", self.action_learning_query, module="self_learning", description="查询自学习状态(中文)")
        ACTIONS.register_action("重置学习", self.action_learning_reset, module="self_learning", description="重置自学习状态(中文)")
        ACTIONS.register_action("更新学习配置", self.action_learning_update, module="self_learning", description="更新自学习配置(中文)")
        self._registered = True
        log.info("[self_learning] 动作注册完成：learning.query / learning.reset / learning.update_config / learning.history / learning.params")

# ==== 热插拔脚手架 ====
def register_actions(dispatcher, context=None):
    mod = SelfLearningModule(meta=getattr(dispatcher, "get_module_meta", lambda *_: None)("self_learning"), context=context)
    dispatcher.register_action("learning.query", mod.action_learning_query, description="查询自学习状态", permission="user", module="self_learning")
    dispatcher.register_action("learning.reset", mod.action_learning_reset, description="重置自学习状态", permission="admin", module="self_learning")
    dispatcher.register_action("learning.update_config", mod.action_learning_update, description="更新自学习配置", permission="admin", module="self_learning")
    dispatcher.register_action("learning.history", mod.action_learning_history, description="获取近期任务历史", permission="user", module="self_learning")
    dispatcher.register_action("learning.params", mod.action_learning_params, description="获取当前内核参数", permission="user", module="self_learning")
    # 中文
    dispatcher.register_action("查询学习状态", mod.action_learning_query, module="self_learning", description="查询自学习状态(中文)")
    dispatcher.register_action("重置学习", mod.action_learning_reset, module="self_learning", description="重置自学习状态(中文)")
    dispatcher.register_action("更新学习配置", mod.action_learning_update, module="self_learning", description="更新自学习配置(中文)")
    log.info("[self_learning] register_actions 完成")

# ==== 内嵌元数据（无需外置 manifest 也可被发现）====
MODULE_METADATA = {
    "name": "self_learning",
    "version": SelfLearningModule.VERSION,
    "title": "三花聚顶 · 自学习模块",
    "author": "三花聚顶开发团队",
    "entry": "modules.self_learning",
    "actions": [
        {"name": "learning.query", "description": "查询自学习状态", "permission": "user"},
        {"name": "learning.reset", "description": "重置自学习状态", "permission": "admin"},
        {"name": "learning.update_config", "description": "更新自学习配置", "permission": "admin"},
        {"name": "learning.history", "description": "获取近期任务历史", "permission": "user"},
        {"name": "learning.params", "description": "获取当前内核参数", "permission": "user"},
    ],
    "dependencies": ["psutil"] if _HAVE_PSUTIL else [],
    "config_schema": {
        "response_time_threshold": {"type": "number", "default": 0.8 if IS_FEDORA else 1.0},
        "adjustment_step": {"type": "number", "default": 0.03 if IS_FEDORA else 0.05},
        "success_rate_target": {"type": "number", "default": 0.97 if IS_FEDORA else 0.95},
        "history_size": {"type": "integer", "default": 1500 if IS_FEDORA else 1000},
        "window_size": {"type": "integer", "default": 150 if IS_FEDORA else 100},
        "min_adjust_interval": {"type": "integer", "default": 10 if IS_FEDORA else 15},
    },
}

MODULE_CLASS = SelfLearningModule

if __name__ == "__main__":
    m = SelfLearningModule(meta=type("M", (), {"config": {}})(), context=None)
    m.preload(); m.setup(); m.start()
    print(json.dumps(m.health_check(), ensure_ascii=False, indent=2))
