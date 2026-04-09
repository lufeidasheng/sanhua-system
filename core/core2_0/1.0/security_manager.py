from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)
# core/security_manager.py

import logging
import time
import threading
import json
import os
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Tuple, Optional, Callable

class SecurityManager:
    """增强型安全管理系统"""
    
    def __init__(self, 
                 max_log_size: int = 1000, 
                 log_file: str = "security.log",
                 policy_file: str = "security_policy.json"):
        """
        初始化安全管理器
        
        Args:
            max_log_size: 内存中保留的最大日志条目数
            log_file: 持久化日志文件路径
            policy_file: 安全策略配置文件路径
        """
        self.access_log = deque(maxlen=max_log_size)
        self.log_file = log_file
        self.policy_file = policy_file
        self.lock = threading.RLock()
        self.policies = self._load_policies()
        self.risk_thresholds = {
            "module": 50,    # 单个模块每分钟最大调用次数
            "action": 30,     # 单个动作每分钟最大调用次数
            "global": 200     # 全局每分钟最大调用次数
        }
        self.risk_counters = self._init_counters()
        self.last_reset_time = datetime.now()
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # 初始化日志器
        self.logger = logging.getLogger("SecurityManager")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        
        # 添加文件处理器
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # 添加控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.logger.info("🔒 安全管理系统已启动")

    def _load_policies(self) -> Dict[str, Dict[str, bool]]:
        """从文件加载安全策略"""
        try:
            if os.path.exists(self.policy_file):
                with open(self.policy_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"加载安全策略失败: {str(e)}")
        
        # 默认策略：允许所有访问
        return {"*": {"*": True}}

    def save_policies(self):
        """保存安全策略到文件"""
        try:
            with open(self.policy_file, 'w') as f:
                json.dump(self.policies, f, indent=2)
        except Exception as e:
            self.logger.error(f"保存安全策略失败: {str(e)}")

    def _init_counters(self) -> Dict[str, Dict[str, int]]:
        """初始化风险计数器"""
        return {
            "module": {},
            "action": {},
            "global": {"count": 0}
        }

    def _reset_counters(self):
        """定期重置计数器"""
        current_time = datetime.now()
        if (current_time - self.last_reset_time) >= timedelta(minutes=1):
            self.risk_counters = self._init_counters()
            self.last_reset_time = current_time

    def _update_counters(self, module: str, action: str):
        """更新风险计数器"""
        self._reset_counters()
        
        with self.lock:
            # 更新模块计数器
            self.risk_counters["module"][module] = self.risk_counters["module"].get(module, 0) + 1
            
            # 更新动作计数器
            action_key = f"{module}.{action}"
            self.risk_counters["action"][action_key] = self.risk_counters["action"].get(action_key, 0) + 1
            
            # 更新全局计数器
            self.risk_counters["global"]["count"] += 1

    def check_risk(self, module: str, action: str) -> bool:
        """检查是否存在安全风险"""
        self._update_counters(module, action)
        
        # 检查模块调用频率
        module_count = self.risk_counters["module"].get(module, 0)
        if module_count > self.risk_thresholds["module"]:
            self.logger.warning(f"⚠️ 模块 {module} 调用频率过高: {module_count}/分钟")
            return True
            
        # 检查动作调用频率
        action_key = f"{module}.{action}"
        action_count = self.risk_counters["action"].get(action_key, 0)
        if action_count > self.risk_thresholds["action"]:
            self.logger.warning(f"⚠️ 动作 {action_key} 调用频率过高: {action_count}/分钟")
            return True
            
        # 检查全局调用频率
        global_count = self.risk_counters["global"]["count"]
        if global_count > self.risk_thresholds["global"]:
            self.logger.warning(f"⚠️ 全局调用频率过高: {global_count}/分钟")
            return True
            
        return False

    def check_access(self, 
                    module_name: str, 
                    action: str,
                    user: Optional[str] = "system",
                    context: Optional[dict] = None) -> Tuple[bool, str]:
        """
        校验模块是否有权限执行特定行为
        
        Args:
            module_name: 模块名称
            action: 请求的动作
            user: 执行用户（可选）
            context: 附加上下文信息（可选）
            
        Returns:
            (是否允许, 拒绝原因)
        """
        # 检查安全风险
        if self.check_risk(module_name, action):
            self._log_access(module_name, action, False, user, "风险检测: 频率过高")
            return False, "操作频率过高，请稍后再试"
        
        # 检查显式拒绝规则
        if module_name in self.policies:
            module_policy = self.policies[module_name]
            
            # 检查特定动作策略
            if action in module_policy:
                if not module_policy[action]:
                    self._log_access(module_name, action, False, user, "策略拒绝")
                    return False, "权限策略禁止此操作"
                self._log_access(module_name, action, True, user)
                return True, ""
            
            # 检查通配符策略
            if "*" in module_policy:
                if not module_policy["*"]:
                    self._log_access(module_name, action, False, user, "模块策略拒绝")
                    return False, "模块权限策略禁止此操作"
                self._log_access(module_name, action, True, user)
                return True, ""
        
        # 检查全局策略
        global_policy = self.policies.get("*", {})
        if action in global_policy:
            if not global_policy[action]:
                self._log_access(module_name, action, False, user, "全局策略拒绝")
                return False, "全局权限策略禁止此操作"
            self._log_access(module_name, action, True, user)
            return True, ""
        
        # 默认通配符策略
        if "*" in global_policy:
            if not global_policy["*"]:
                self._log_access(module_name, action, False, user, "全局默认策略拒绝")
                return False, "默认权限策略禁止此操作"
            self._log_access(module_name, action, True, user)
            return True, ""
        
        # 默认允许
        self._log_access(module_name, action, True, user)
        return True, ""

    def _log_access(self, 
                   module: str, 
                   action: str, 
                   allowed: bool,
                   user: str = "system",
                   reason: str = ""):
        """
        记录访问日志
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        entry = {
            "timestamp": timestamp,
            "module": module,
            "action": action,
            "user": user,
            "allowed": allowed,
            "reason": reason
        }
        
        with self.lock:
            self.access_log.append(entry)
        
        # 记录到文件日志
        status = "✅ 允许" if allowed else "⛔ 拒绝"
        log_msg = f"[金钟罩] 用户: {user} 模块: {module} 动作: {action} => {status}"
        if reason:
            log_msg += f" | 原因: {reason}"
        
        if allowed:
            self.logger.info(log_msg)
        else:
            self.logger.warning(log_msg)

    def add_policy(self, 
                  module: str, 
                  action: str, 
                  allowed: bool,
                  persist: bool = True):
        """
        添加或更新权限策略
        
        Args:
            module: 模块名称（"*"表示全局）
            action: 动作名称（"*"表示所有动作）
            allowed: 是否允许
            persist: 是否持久化到文件
        """
        with self.lock:
            if module not in self.policies:
                self.policies[module] = {}
                
            self.policies[module][action] = allowed
        
        if persist:
            self.save_policies()
            
        self.logger.info(f"更新策略: {module}.{action} = {'允许' if allowed else '禁止'}")

    def remove_policy(self, module: str, action: str):
        """
        移除权限策略
        """
        with self.lock:
            if module in self.policies and action in self.policies[module]:
                del self.policies[module][action]
                self.save_policies()
                self.logger.info(f"移除策略: {module}.{action}")

    def get_logs(self, 
                max_entries: int = 100,
                filter_module: Optional[str] = None,
                filter_action: Optional[str] = None,
                filter_user: Optional[str] = None) -> List[dict]:
        """
        获取访问日志
        
        Args:
            max_entries: 最大返回条目数
            filter_module: 按模块过滤
            filter_action: 按动作过滤
            filter_user: 按用户过滤
            
        Returns:
            过滤后的日志列表（最近的在前面）
        """
        with self.lock:
            logs = list(self.access_log)
        
        # 反转顺序，使最新的日志在前
        logs.reverse()
        
        # 应用过滤
        filtered = []
        for log in logs:
            if filter_module and log["module"] != filter_module:
                continue
            if filter_action and log["action"] != filter_action:
                continue
            if filter_user and log["user"] != filter_user:
                continue
            filtered.append(log)
            if len(filtered) >= max_entries:
                break
                
        return filtered

    def audit_trail(self, 
                   start_time: Optional[datetime] = None,
                   end_time: Optional[datetime] = None) -> List[dict]:
        """
        获取审计跟踪（从持久化日志）
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
            
        Returns:
            指定时间范围内的日志条目
        """
        # 简化的实现 - 实际项目中应考虑使用专业日志系统
        results = []
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    for line in f:
                        try:
                            # 简化解析 - 实际应使用日志解析器
                            if "[金钟罩]" in line:
                                entry = {
                                    "raw": line.strip(),
                                    "timestamp": line.split("]")[0][1:]
                                }
                                results.append(entry)
                        except:
                            continue
        except Exception as e:
            self.logger.error(f"审计跟踪失败: {str(e)}")
            
        return results

# 示例用法
if __name__ == "__main__":
    # 初始化安全管理器
    security = SecurityManager(
        max_log_size=500,
        log_file="logs/security.log",
        policy_file="config/security_policy.json"
    )
    
    # 添加策略
    security.add_policy("payment", "process", True)  # 允许支付处理
    security.add_policy("admin", "*", False)         # 禁止所有admin模块操作
    
    # 测试访问检查
    result, reason = security.check_access("payment", "process", user="customer123")
    print(f"支付处理: {'通过' if result else '拒绝'} - {reason}")
    
    result, reason = security.check_access("admin", "delete_user", user="hacker")
    print(f"删除用户: {'通过' if result else '拒绝'} - {reason}")
    
    # 测试日志查询
    print("\n最近5条日志:")
    for log in security.get_logs(max_entries=5):
        print(f"{log['timestamp']} | {log['user']} | {log['module']}.{log['action']} | {log['allowed']}")
    
    # 测试风险检测（模拟高频调用）
    for _ in range(60):
        security.check_access("report", "generate", user="automation")
    
    result, reason = security.check_access("report", "generate", user="automation")
    print(f"\n报告生成: {'通过' if result else '拒绝'} - {reason}")
