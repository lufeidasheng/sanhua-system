import os
import psutil

class SystemMonitor:
    """用于监控当前进程的资源使用情况"""
    def __init__(self):
        self.process = psutil.Process(os.getpid())

    def get_status_text(self):
        try:
            mem_mb = self.process.memory_info().rss / 1024 / 1024
            cpu_percent = self.process.cpu_percent(interval=0.1)
            return f"内存: {mem_mb:.2f} MB, CPU: {cpu_percent:.2f}%"
        except Exception as e:
            print(f"[聚核助手] 获取系统状态失败: {e}")
            return "状态获取失败"
