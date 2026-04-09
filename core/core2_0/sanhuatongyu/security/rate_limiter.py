# core/core2_0/sanhuatongyu/security/rate_limiter.py

import time
import threading

class TokenBucketLimiter:
    """
    三花聚顶 · 令牌桶速率限制器（线程安全）
    用于全局/事件/接口/动作等多级限流，防止滥用与瞬时洪峰
    """

    def __init__(self, capacity: int, fill_rate: float):
        """
        :param capacity: 桶的最大容量（允许瞬时突发的最大令牌数）
        :param fill_rate: 每秒补充的令牌数（持续速率）
        """
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self.fill_rate = float(fill_rate)
        self.last_time = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        尝试消费指定数量的令牌
        :param tokens: 请求消耗的令牌数
        :return: 是否成功消费（可用则消费并返回True，否则返回False）
        """
        with self.lock:
            self._replenish()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _replenish(self):
        """
        根据距离上次请求的时间差补充令牌
        """
        now = time.time()
        delta = self.fill_rate * (now - self.last_time)
        if delta > 0:
            self._tokens = min(self.capacity, self._tokens + delta)
            self.last_time = now

    def update_rate(self, new_rate: float):
        """
        动态调整补充速率
        :param new_rate: 新的每秒填充速率
        """
        with self.lock:
            self._replenish()
            self.fill_rate = float(new_rate)

    @property
    def tokens(self) -> float:
        """
        当前桶内令牌数量
        :return: float
        """
        with self.lock:
            self._replenish()
            return self._tokens

# ==== 单元测试 ====
if __name__ == "__main__":
    limiter = TokenBucketLimiter(capacity=10, fill_rate=5)
    ok_count = 0
    for _ in range(20):
        if limiter.consume():
            ok_count += 1
        else:
            print("限流触发，等待补充…")
            time.sleep(0.3)
    print(f"测试完成：允许通过 {ok_count} 次，剩余令牌：{limiter.tokens:.2f}")
