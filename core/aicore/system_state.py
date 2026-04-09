import psutil
from datetime import datetime
from typing import Dict

class SystemState:
    def __init__(self):
        self.cpu_usage = 0
        self.memory_usage = 0
        self.disk_space = 0
        self.uptime = 0
    
    def update(self):
        """更新系统状态"""
        self.cpu_usage = psutil.cpu_percent()
        self.memory_usage = psutil.virtual_memory().percent
        self.disk_space = psutil.disk_usage('/').percent
        self.uptime = datetime.now()  # 当前时间作为简易系统上线时间戳
    
    def get_state(self) -> Dict[str, float]:
        """返回当前系统状态"""
        return {
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "disk_space": self.disk_space,
            "uptime": self.uptime,
        }
