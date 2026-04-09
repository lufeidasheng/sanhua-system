import threading
import time
import logging
from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)

class SelfHealingScheduler(threading.Thread):
    def __init__(self, rollback_manager, log_analyzer, interval=60):
        """
        自愈系统调度器
        :param rollback_manager: 回滚管理器实例
        :param log_analyzer: 日志分析器实例
        :param interval: 检测间隔(秒)
        """
        super().__init__(daemon=True)
        self.rollback_manager = rollback_manager
        self.log_analyzer = log_analyzer
        self.interval = interval
        self._stop_event = threading.Event()
        self.lock = threading.RLock()  # 可重入锁
        self.last_heal_time = 0
        self.heal_cooldown = 300  # 5分钟冷却时间

    def run(self):
        """调度器主循环"""
        log.info("🛡️ 自愈系统调度器启动")
        try:
            while not self._stop_event.is_set():
                try:
                    self.check_and_heal()
                except Exception as e:
                    log.error(f"自愈调度器异常: {e}", exc_info=True)
                # 等待下一次检测
                time.sleep(self.interval)
        finally:
            log.info("🛑 自愈系统调度器停止")

    def check_and_heal(self):
        """执行自愈检测和修复"""
        current_time = time.time()
        
        # 检查冷却时间
        if current_time - self.last_heal_time < self.heal_cooldown:
            return
            
        with self.lock:  # 确保线程安全
            # 1. 检查是否需要回滚（基于日志分析）
            if self._needs_rollback():
                log.warning("⏪ 检测到需要自动回滚，开始执行回滚流程")
                if self.rollback_manager.perform_rollback():
                    self.log_analyzer.reset_detection()  # 重置检测状态
                    self.last_heal_time = current_time
            
            # 2. 检查是否需要其他修复
            elif self.log_analyzer.is_repair_needed():
                log.warning("🔧 日志分析检测到异常，开始执行自动修复")
                self.log_analyzer.perform_repair(self.rollback_manager)
                self.last_heal_time = current_time

    def _needs_rollback(self) -> bool:
        """判断是否需要执行回滚操作"""
        # 检查回滚是否可用（冷却时间）
        if not self.rollback_manager.can_rollback():
            return False
        
        # 检查是否有需要回滚的关键错误
        return self.log_analyzer.has_critical_errors()

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        log.info("🛑 自愈调度器停止请求已发送")
