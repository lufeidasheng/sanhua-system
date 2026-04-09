# core/core2_0/sanhuatongyu/monitoring/thread_monitor.py
"""
三花聚顶 · 企业级线程监控系统
支持：动态发现线程、资源占用跟踪、僵尸检测、异常自愈、指标统计
"""

import threading
import time
import platform
from typing import Dict, Any, Optional
try:
    import psutil
except ImportError:
    psutil = None

from core.core2_0.sanhuatongyu.logger import get_logger

class ThreadMonitor:
    """
    🌸 三花聚顶 · 企业级线程监控系统
    支持跨平台（psutil可选），健康统计、异常自愈、运行信息采集
    """
    def __init__(self):
        self.logger = get_logger('thread_monitor')
        self.monitor_thread: Optional[threading.Thread] = None
        self.running = False
        self.threads: Dict[int, Dict[str, Any]] = {}
        self.metrics: Dict[str, Any] = {
            "thread_started": 0,
            "thread_terminated": 0,
            "zombie_detected": 0,
            "last_check": 0,
            "peak_threads": 0,
        }

    def start(self):
        """启动线程监控（幂等）"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.logger.info("monitor_already_running")
            return

        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_threads,
            daemon=True,
            name="Thread-Monitor"
        )
        self.monitor_thread.start()
        self.logger.info("thread_monitor_started")

    def stop(self):
        """停止线程监控"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        self.logger.info("thread_monitor_stopped")

    def _monitor_threads(self):
        """监控所有活动线程、检测资源占用与异常"""
        platform_info = platform.system().lower()
        while self.running:
            try:
                now = time.time()
                current_threads = {t.ident: t for t in threading.enumerate() if t.ident}
                # 新增线程
                new_threads = set(current_threads) - set(self.threads)
                for tid in new_threads:
                    thread = current_threads[tid]
                    self.threads[tid] = {
                        "name": thread.name,
                        "start_time": now,
                        "cpu_time": 0,
                        "state": thread.is_alive(),
                        "last_active": now
                    }
                    self.metrics["thread_started"] += 1
                    self.logger.info("thread_started", thread_id=tid, thread_name=thread.name)
                # 结束线程
                dead_threads = set(self.threads) - set(current_threads)
                for tid in dead_threads:
                    thread_info = self.threads.pop(tid)
                    duration = now - thread_info["start_time"]
                    self.metrics["thread_terminated"] += 1
                    self.logger.info(
                        "thread_terminated",
                        thread_id=tid,
                        thread_name=thread_info["name"],
                        duration=round(duration, 2)
                    )
                # 更新资源占用
                peak_threads = len(current_threads)
                if peak_threads > self.metrics["peak_threads"]:
                    self.metrics["peak_threads"] = peak_threads
                if psutil and hasattr(psutil, "Process"):
                    try:
                        p = psutil.Process()
                        for tid, thread in current_threads.items():
                            # psutil 线程资源
                            cpu_times = None
                            try:
                                for th in p.threads():
                                    if th.id == tid:
                                        cpu_times = th.user_time + th.system_time
                                        break
                                if cpu_times is not None:
                                    self.threads[tid]["cpu_time"] = cpu_times
                                    self.threads[tid]["last_active"] = now
                            except Exception:
                                pass
                    except Exception:
                        pass
                # 僵尸线程检测（长时间存活且无CPU）
                for tid, info in self.threads.items():
                    thread_lifetime = now - info["start_time"]
                    cpu_time = info.get("cpu_time", 0)
                    if thread_lifetime > 300 and cpu_time < 0.1:  # 5分钟且近乎无消耗
                        self.metrics["zombie_detected"] += 1
                        self.logger.warning(
                            "zombie_thread_detected",
                            thread_id=tid,
                            thread_name=info["name"],
                            lifetime=round(thread_lifetime, 1)
                        )
                self.metrics["last_check"] = now
                time.sleep(10)  # 检查周期
            except Exception as e:
                self.logger.error("thread_monitor_error", extra={"error": str(e)})
                time.sleep(30)

    def get_metrics(self) -> Dict[str, Any]:
        """获取监控指标（线程统计/僵尸数等）"""
        return dict(self.metrics)

    def get_active_threads(self) -> Dict[int, Dict[str, Any]]:
        """获取当前活动线程信息快照"""
        return self.threads.copy()

# 用法示例
if __name__ == "__main__":
    monitor = ThreadMonitor()
    monitor.start()
    try:
        for i in range(3):
            t = threading.Thread(target=lambda: time.sleep(60), name=f"Worker-{i}")
            t.start()
        time.sleep(15)
        print("Metrics:", monitor.get_metrics())
        print("Threads:", monitor.get_active_threads())
        time.sleep(10)
    finally:
        monitor.stop()
