# core/aicore/circuit_breaker.py

import time
from typing import Optional

class CircuitBreaker:
    """
    三花聚顶 · AICore 模块熔断器（简洁型，预留可扩展接口）
    支持基本的自动开关、半开自愈、统计失败率、与健康监控结合
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_try_limit: int = 2
    ):
        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_try_limit = half_open_try_limit
        self._half_open_attempts = 0

    @property
    def state(self) -> str:
        """当前熔断状态：closed/open/half_open"""
        # 自动检测超时窗口是否到期，转入半开
        if self._state == "open" and self._last_failure_time:
            if (time.time() - self._last_failure_time) > self.recovery_timeout:
                self._state = "half_open"
                self._half_open_attempts = 0
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    @property
    def is_half_open(self) -> bool:
        return self.state == "half_open"

    @property
    def is_closed(self) -> bool:
        return self.state == "closed"

    def allow_request(self) -> bool:
        """判断是否允许通过请求"""
        if self.state == "closed":
            return True
        elif self.state == "open":
            # open 状态只允许定时自愈检查
            return False
        elif self.state == "half_open":
            # 半开状态允许有限试探
            if self._half_open_attempts < self.half_open_try_limit:
                self._half_open_attempts += 1
                return True
            else:
                return False
        return False

    def record_failure(self):
        """记录一次失败，如果超过阈值则进入 open 熔断"""
        self._failure_count += 1
        if self._state == "closed" and self._failure_count >= self.failure_threshold:
            self._state = "open"
            self._last_failure_time = time.time()
        elif self._state == "half_open":
            self._state = "open"
            self._last_failure_time = time.time()

    def record_success(self):
        """记录一次成功，如果在半开状态下则恢复闭合"""
        self._success_count += 1
        if self._state == "half_open":
            # 半开期间全部成功即可恢复
            self._state = "closed"
            self._failure_count = 0
            self._half_open_attempts = 0

    def reset(self):
        """强制重置熔断器状态"""
        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._half_open_attempts = 0
        self._last_failure_time = None

    def metrics(self):
        """返回熔断器运行状态指标"""
        return {
            "state": self.state,
            "failures": self._failure_count,
            "successes": self._success_count,
            "last_failure": self._last_failure_time,
            "half_open_attempts": self._half_open_attempts
        }

# ==== 简单单元测试 ====
if __name__ == "__main__":
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=2, half_open_try_limit=1)
    print("初始状态：", cb.state)
    for i in range(3):
        cb.record_failure()
        print(f"失败{i+1}，状态：{cb.state}")
    print("允许请求？", cb.allow_request())
    time.sleep(2.2)
    print("过期自愈后，允许？", cb.allow_request())
    cb.record_success()
    print("恢复成功，状态：", cb.state)
    print("熔断器指标：", cb.metrics())
