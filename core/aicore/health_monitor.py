#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
from typing import Optional, Dict, Any, Callable


class HealthMonitorPlus:
    """
    三花聚顶 · 健康监控模块（企业稳定版）
    - 多维指标统计（成功/失败/拒绝/队列）
    - 过载判据：失败率、队列占用、连续拒绝（可配置）
    - “持续过载”状态机：只有持续超过阈值 >= overload_duration 才进入 overloaded
    - 线程安全：使用 RLock + 单次快照避免锁内递归
    - 支持外部事件钩子（同步调用，保证最小惊吓）
    """

    def __init__(
        self,
        queue_max: int = 100,
        failure_threshold: float = 0.2,
        reject_threshold: int = 10,
        overload_duration: int = 10,
        external_hook: Optional[Callable[[str, str], Any]] = None,
        # 可选增强：统计窗口（秒），用于更真实的失败率，不被“历史成功”稀释
        window_seconds: int = 60,
    ):
        # counters
        self._success_count = 0
        self._failure_count = 0
        self._rejection_count = 0
        self._total_count = 0

        # consecutive rejection (真正“连续”的概念)
        self._consecutive_rejects = 0

        # queue
        self._queue_length = 0
        self._queue_max = int(queue_max)

        # thresholds
        self._failure_threshold = float(failure_threshold)
        self._reject_threshold = int(reject_threshold)
        self._overload_duration = int(overload_duration)

        # overload state machine
        self._overload_since: Optional[float] = None   # 第一次满足过载条件的时间
        self._overloaded_flag: bool = False            # 当前是否已进入 overlaoded

        # rolling window stats（用于更真实的 failure_rate）
        self._window_seconds = int(window_seconds)
        self._window_events = []  # list[(ts, ok_bool)]  ok=True=success, ok=False=failure

        # thread safety
        self._lock = threading.RLock()

        # hook
        self._external_hook = external_hook

    # -------------------------
    # 内部：窗口维护
    # -------------------------
    def _prune_window_locked(self, now: float) -> None:
        """清理窗口外事件，必须在锁内调用"""
        if self._window_seconds <= 0:
            return
        cutoff = now - self._window_seconds
        # list 很短时足够；若未来事件量很大可换 deque
        i = 0
        for i, (ts, _) in enumerate(self._window_events):
            if ts >= cutoff:
                break
        else:
            # 全部过期
            self._window_events.clear()
            return
        if self._window_events and self._window_events[0][0] < cutoff:
            self._window_events = self._window_events[i:]

    def _record_window_event_locked(self, ok: bool, now: float) -> None:
        """记录窗口事件，必须在锁内调用"""
        if self._window_seconds <= 0:
            return
        self._window_events.append((now, ok))
        self._prune_window_locked(now)

    # -------------------------
    # 记录事件
    # -------------------------
    def record_success(self) -> None:
        now = time.time()
        with self._lock:
            self._success_count += 1
            self._total_count += 1
            # 成功意味着拒绝不连续了（否则“连续拒绝”永远累加）
            self._consecutive_rejects = 0
            self._record_window_event_locked(True, now)
            # 成功并不一定立刻解除 overlaod；由状态机在 is_overloaded 里判断

    def record_failure(self, detail: Optional[str] = None) -> None:
        now = time.time()
        hook = self._external_hook
        with self._lock:
            self._failure_count += 1
            self._total_count += 1
            # 失败可以视为系统仍在处理请求，因此也中断“连续拒绝”
            self._consecutive_rejects = 0
            self._record_window_event_locked(False, now)

        if hook:
            try:
                hook("failure", detail or "未知错误")
            except Exception:
                # hook 不应影响主流程
                pass

    def record_rejection(self, reason: Optional[str] = None) -> None:
        now = time.time()
        hook = self._external_hook
        with self._lock:
            self._rejection_count += 1
            self._consecutive_rejects += 1
            # 拒绝不计入 total_count（可按你口径调整）；这里保守不算“处理过请求”
            self._record_window_event_locked(False, now)  # 拒绝算“失败”对系统体验更真实

        if hook:
            try:
                hook("rejection", reason or "队列已满")
            except Exception:
                pass

    def update_queue_length(self, length: int) -> None:
        with self._lock:
            self._queue_length = max(0, int(length))

    # -------------------------
    # 快照计算（避免锁内递归）
    # -------------------------
    def _snapshot_locked(self) -> Dict[str, Any]:
        """在锁内抓取所有基础数据，供锁外/同锁内一次性计算"""
        return {
            "success": self._success_count,
            "failure": self._failure_count,
            "rejection": self._rejection_count,
            "total": self._total_count,
            "queue_length": self._queue_length,
            "queue_max": self._queue_max,
            "consecutive_rejects": self._consecutive_rejects,
            "failure_threshold": self._failure_threshold,
            "reject_threshold": self._reject_threshold,
            "overload_duration": self._overload_duration,
            "overload_since": self._overload_since,
            "overloaded_flag": self._overloaded_flag,
            "window_seconds": self._window_seconds,
            "window_events": list(self._window_events),
        }

    @staticmethod
    def _calc_failure_rate(success: int, failure: int) -> float:
        total = success + failure
        return (failure / total) if total > 0 else 0.0

    @staticmethod
    def _calc_queue_util(queue_length: int, queue_max: int) -> float:
        return (queue_length / queue_max) if queue_max > 0 else 0.0

    def _calc_window_failure_rate(self, window_events) -> float:
        if not window_events:
            return 0.0
        fail = sum(1 for _, ok in window_events if not ok)
        total = len(window_events)
        return fail / total if total else 0.0

    # -------------------------
    # 对外属性（只读）
    # -------------------------
    @property
    def current_failure_rate(self) -> float:
        with self._lock:
            # 优先窗口失败率（更贴近“最近状态”），窗口关闭则回退全局
            now = time.time()
            self._prune_window_locked(now)
            if self._window_seconds > 0:
                return self._calc_window_failure_rate(self._window_events)
            return self._calc_failure_rate(self._success_count, self._failure_count)

    @property
    def queue_utilization(self) -> float:
        with self._lock:
            return self._calc_queue_util(self._queue_length, self._queue_max)

    @property
    def queue_full(self) -> bool:
        with self._lock:
            return self._queue_max > 0 and self._queue_length >= self._queue_max

    @property
    def is_overloaded(self) -> bool:
        """
        过载状态机：
        - 先判断当前是否满足“过载条件”
        - 如果满足：记录 overload_since，持续 >= overload_duration 后置为 overloaded
        - 如果不满足：清除 overload_since，并解除 overloaded
        """
        now = time.time()
        with self._lock:
            # 计算当前判据（不要调用其他 property，避免锁内嵌套）
            self._prune_window_locked(now)

            if self._window_seconds > 0:
                failure_rate = self._calc_window_failure_rate(self._window_events)
            else:
                failure_rate = self._calc_failure_rate(self._success_count, self._failure_count)

            queue_util = self._calc_queue_util(self._queue_length, self._queue_max)
            # “连续拒绝”比总拒绝更有意义
            consecutive_rejects = self._consecutive_rejects

            cond = (
                (failure_rate > self._failure_threshold) or
                (queue_util > 0.8) or
                (consecutive_rejects > self._reject_threshold)
            )

            if cond:
                if self._overload_since is None:
                    self._overload_since = now

                # 满足条件持续够久才进入 overloaded
                if (now - self._overload_since) >= self._overload_duration:
                    self._overloaded_flag = True
                # 未够久保持当前 flag（防抖）
            else:
                # 恢复：清状态
                self._overload_since = None
                self._overloaded_flag = False
                # 连续拒绝也应在恢复条件下清零（否则会误触发）
                self._consecutive_rejects = 0

            return self._overloaded_flag

    # -------------------------
    # 控制与报告
    # -------------------------
    def reset(self) -> None:
        """重置统计（健康恢复/周期切换后调用）"""
        with self._lock:
            self._success_count = 0
            self._failure_count = 0
            self._rejection_count = 0
            self._total_count = 0
            self._queue_length = 0
            self._consecutive_rejects = 0
            self._overload_since = None
            self._overloaded_flag = False
            self._window_events.clear()

    def health_report(self) -> Dict[str, Any]:
        """返回结构化健康状态（不会死锁）"""
        now = time.time()
        with self._lock:
            self._prune_window_locked(now)
            snap = self._snapshot_locked()

            # 计算派生指标
            if snap["window_seconds"] > 0:
                failure_rate = self._calc_window_failure_rate(snap["window_events"])
                failure_rate_kind = f"window_{snap['window_seconds']}s"
            else:
                failure_rate = self._calc_failure_rate(snap["success"], snap["failure"])
                failure_rate_kind = "lifetime"

            queue_util = self._calc_queue_util(snap["queue_length"], snap["queue_max"])

            # 在 report 里计算一次 is_overloaded（仍在同一把 RLock 内，安全）
            overloaded = self.is_overloaded

            return {
                "success": snap["success"],
                "failure": snap["failure"],
                "rejection": snap["rejection"],
                "total": snap["total"],
                "queue_length": snap["queue_length"],
                "queue_max": snap["queue_max"],
                "queue_utilization": round(queue_util, 4),
                "queue_full": (snap["queue_max"] > 0 and snap["queue_length"] >= snap["queue_max"]),
                "failure_rate": round(failure_rate, 4),
                "failure_rate_kind": failure_rate_kind,
                "consecutive_rejects": snap["consecutive_rejects"],
                "thresholds": {
                    "failure_threshold": snap["failure_threshold"],
                    "reject_threshold": snap["reject_threshold"],
                    "overload_duration": snap["overload_duration"],
                },
                "overload": {
                    "is_overloaded": bool(overloaded),
                    "overload_since": snap["overload_since"],
                    "overloaded_flag": snap["overloaded_flag"],
                },
                "timestamp": now,
            }


# ==== 示例用法 ====
if __name__ == "__main__":
    def hook(event_type, detail):
        print(f"外部事件上报: {event_type} - {detail}")

    monitor = HealthMonitorPlus(queue_max=5, external_hook=hook, overload_duration=2, reject_threshold=1)

    for _ in range(3):
        monitor.record_success()

    monitor.record_failure("模型推理失败")
    monitor.update_queue_length(4)

    monitor.record_rejection("队列满")
    print("第一次报告（未必过载，因为需要持续）:", monitor.health_report())

    time.sleep(2.2)
    # 在持续时间后，再触发一次拒绝以维持 cond
    monitor.record_rejection("队列仍满")
    print("第二次报告（应进入过载）:", monitor.health_report())