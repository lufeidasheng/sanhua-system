import threading
import logging
import re
import os
import time
from collections import defaultdict
from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)

class LogAnalyzer:
    def __init__(self, log_file="assistant.log"):
        self.log_file = log_file
        self.lock = threading.RLock()  # 使用可重入锁
        self.last_position = 0  # 上次读取位置
        self.error_counts = defaultdict(int)  # 错误类型计数
        self.last_detect_time = 0
        self.cooldown = 60  # 60秒冷却时间，防止频繁触发修复
        
        # 定义错误模式的正则表达式
        self.error_patterns = {
            "module_load_fail": re.compile(r"模块加载失败|failed to load module", re.I),
            "action_error": re.compile(r"动作执行失败|action error|exception", re.I),
            "system_call_fail": re.compile(r"重启失败|关机失败|error calling system", re.I),
            "resource_exhaustion": re.compile(r"内存不足|out of memory|磁盘空间不足|disk full", re.I),
            "connection_failure": re.compile(r"连接失败|connection refused|timeout", re.I),
        }
        
        # 关键错误类型（需要立即回滚）
        self.critical_errors = {
            "resource_exhaustion": 1,  # 资源耗尽立即回滚
            "system_call_fail": 1,     # 系统调用失败立即回滚
        }
        
        # 确保日志文件存在
        if not os.path.exists(self.log_file):
            open(self.log_file, 'a').close()
            log.info(f"创建日志文件: {self.log_file}")

    def read_new_logs(self) -> str:
        """读取日志文件新增内容"""
        with self.lock:
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    f.seek(self.last_position)
                    new_logs = f.read()
                    self.last_position = f.tell()
                    return new_logs
            except Exception as e:
                log.error(f"LogAnalyzer 读取日志失败: {e}")
                return ""

    def analyze_logs(self, logs: str):
        """分析日志文本，统计错误次数"""
        if not logs:
            return
            
        for key, pattern in self.error_patterns.items():
            matches = pattern.findall(logs)
            if matches:
                with self.lock:
                    self.error_counts[key] += len(matches)
                log.info(f"LogAnalyzer 发现 {key} 错误 {len(matches)} 次")

    def is_repair_needed(self) -> bool:
        """
        判断是否需要触发自动修复
        :return: 是否需要修复
        """
        now = time.time()
        new_logs = self.read_new_logs()
        self.analyze_logs(new_logs)

        with self.lock:
            # 检查是否有错误达到阈值且在冷却时间外
            for error_type, count in self.error_counts.items():
                # 关键错误立即触发
                if error_type in self.critical_errors and count >= self.critical_errors[error_type]:
                    log.warning(f"LogAnalyzer 检测到关键错误: {error_type}")
                    return True
                
                # 一般错误需要达到阈值
                if count >= 3 and (now - self.last_detect_time) > self.cooldown:
                    log.warning(f"LogAnalyzer 触发修复: {error_type} 错误累计 {count} 次")
                    self.last_detect_time = now
                    return True
                    
            return False

    def has_critical_errors(self) -> bool:
        """检查是否有需要回滚的关键错误"""
        with self.lock:
            for error_type, threshold in self.critical_errors.items():
                if self.error_counts.get(error_type, 0) >= threshold:
                    return True
            return False

    def perform_repair(self, rollback_manager):
        """
        执行自动修复操作
        :param rollback_manager: 回滚管理器实例
        """
        if not rollback_manager:
            log.error("LogAnalyzer 无法执行修复：缺少 RollbackManager")
            return
            
        log.info("LogAnalyzer 开始自动修复...")
        try:
            # 尝试回滚到最近的快照
            if rollback_manager.rollback_last_action():
                log.info("LogAnalyzer 自动修复完成 - 已回滚到最近快照")
            else:
                log.warning("LogAnalyzer 自动修复失败 - 回滚未执行")
        except Exception as e:
            log.error(f"LogAnalyzer 修复失败: {e}")
        finally:
            self.reset_detection()

    def reset_detection(self):
        """重置错误计数和检测状态"""
        with self.lock:
            self.error_counts.clear()
            # 重置日志读取位置，确保下一次读取完整日志
            self.last_position = 0
            log.info("LogAnalyzer 检测状态已重置")

    def get_error_counts(self):
        """获取当前错误计数（用于调试）"""
        with self.lock:
            return dict(self.error_counts)

# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 创建测试日志
    with open("test.log", "w") as f:
        f.write("2023-01-01 12:00:00 INFO: 系统启动\n")
        f.write("2023-01-01 12:00:05 ERROR: 模块加载失败\n")
        f.write("2023-01-01 12:00:10 CRITICAL: 内存不足\n")
    
    analyzer = LogAnalyzer(log_file="test.log")
    
    # 第一次检测
    if analyzer.is_repair_needed():
        print("需要修复！")
        # 模拟回滚管理器
        class MockRollbackManager:
            def rollback_last_action(self):
                print("执行回滚操作")
                return True
                
        analyzer.perform_repair(MockRollbackManager())
    else:
        print("无需修复")
    
    # 检查错误计数
    print("错误计数:", analyzer.get_error_counts())
    
    # 第二次检测
    if analyzer.is_repair_needed():
        print("需要修复！")
    else:
        print("无需修复")
