import os
import json
import threading
import logging
import time
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Tuple, Optional, Callable

from .access_control import AccessControl
from .rate_limiter import TokenBucketLimiter

class SecurityManager:
    """
    三花聚顶 · 企业级安全管理系统
    - 访问权限检查（RBAC，集成AccessControl）
    - 动作/模块/全局频率风控
    - 策略热更新/持久化
    - 审计追踪与安全日志
    """

    def __init__(self,
                 max_log_size: int = 1000,
                 log_file: str = "logs/security.log",
                 policy_file: str = "config/security_policy.json",
                 access_control: Optional[AccessControl] = None):
        # 权限/策略/速率等核心组件
        self.access_control = access_control or AccessControl()
        self.policy_file = policy_file
        self.lock = threading.RLock()

        # 日志
        self.access_log = deque(maxlen=max_log_size)
        self.log_file = log_file
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        self.logger = logging.getLogger("SecurityManager")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
            self.logger.addHandler(logging.StreamHandler())

        self.logger.info("🔒 SecurityManager 初始化完成")

        # 风险策略与频率阈值
        self.risk_thresholds = {
            "module": 50,    # 每分钟
            "action": 30,
            "global": 200
        }
        self.risk_counters = self._init_counters()
        self.last_reset_time = datetime.now()

        # 动态安全策略
        self.policies = self._load_policies()

        # 自动为全局与模块准备速率控制器
        self.global_limiter = TokenBucketLimiter(200, 200/60)
        self.module_limiters: Dict[str, TokenBucketLimiter] = {}
        self.action_limiters: Dict[str, TokenBucketLimiter] = {}

    def _init_counters(self):
        return {
            "module": {},
            "action": {},
            "global": {"count": 0}
        }

    def _load_policies(self) -> Dict[str, Dict[str, bool]]:
        try:
            if os.path.exists(self.policy_file):
                with open(self.policy_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"加载安全策略失败: {str(e)}")
        return {"*": {"*": True}}

    def save_policies(self):
        try:
            with open(self.policy_file, 'w') as f:
                json.dump(self.policies, f, indent=2)
        except Exception as e:
            self.logger.error(f"保存安全策略失败: {str(e)}")

    def _reset_counters(self):
        now = datetime.now()
        if (now - self.last_reset_time) >= timedelta(minutes=1):
            self.risk_counters = self._init_counters()
            self.last_reset_time = now

    def _update_counters(self, module: str, action: str):
        self._reset_counters()
        with self.lock:
            self.risk_counters["module"][module] = self.risk_counters["module"].get(module, 0) + 1
            action_key = f"{module}.{action}"
            self.risk_counters["action"][action_key] = self.risk_counters["action"].get(action_key, 0) + 1
            self.risk_counters["global"]["count"] += 1

            # 速率控制器自适应
            if module not in self.module_limiters:
                self.module_limiters[module] = TokenBucketLimiter(self.risk_thresholds["module"], self.risk_thresholds["module"]/60)
            if action_key not in self.action_limiters:
                self.action_limiters[action_key] = TokenBucketLimiter(self.risk_thresholds["action"], self.risk_thresholds["action"]/60)

    def check_risk(self, module: str, action: str) -> bool:
        """检测风控阈值和速率限制"""
        self._update_counters(module, action)
        limited = False

        # 全局速率
        if not self.global_limiter.consume():
            self.logger.warning(f"⚡️ 全局QPS风控，超过速率限制")
            limited = True

        # 模块级
        mod_limiter = self.module_limiters.get(module)
        if mod_limiter and not mod_limiter.consume():
            self.logger.warning(f"⚡️ 模块[{module}]速率限制，触发风控")
            limited = True

        # 动作级
        act_key = f"{module}.{action}"
        act_limiter = self.action_limiters.get(act_key)
        if act_limiter and not act_limiter.consume():
            self.logger.warning(f"⚡️ 动作[{act_key}]速率限制，触发风控")
            limited = True

        # 调用频率警告
        mod_count = self.risk_counters["module"].get(module, 0)
        if mod_count > self.risk_thresholds["module"]:
            self.logger.warning(f"⚠️ 模块 {module} 调用频率过高: {mod_count}/分钟")
            limited = True

        act_count = self.risk_counters["action"].get(act_key, 0)
        if act_count > self.risk_thresholds["action"]:
            self.logger.warning(f"⚠️ 动作 {act_key} 调用频率过高: {act_count}/分钟")
            limited = True

        global_count = self.risk_counters["global"]["count"]
        if global_count > self.risk_thresholds["global"]:
            self.logger.warning(f"⚠️ 全局调用频率过高: {global_count}/分钟")
            limited = True

        return limited

    def check_access(self,
                     module: str,
                     action: str,
                     user: str = "system",
                     context: Optional[dict] = None,
                     role: str = "system") -> Tuple[bool, str]:
        """
        检查权限 + 风控，集成RBAC+风控
        :returns: (是否允许, 拒绝原因/说明)
        """
        # 风险频控先判定
        if self.check_risk(module, action):
            self._log_access(module, action, False, user, "频控风控触发")
            return False, "操作过于频繁，请稍后再试"

        # RBAC权限控制
        event_type = f"{module}.{action}"
        if not self.access_control.check_event_permission(role, event_type):
            self._log_access(module, action, False, user, "RBAC策略拒绝")
            return False, "无权限操作该事件"

        # 策略细粒度判定
        with self.lock:
            policy_mod = self.policies.get(module, {})
            if action in policy_mod and not policy_mod[action]:
                self._log_access(module, action, False, user, "本地策略拒绝")
                return False, "策略禁止此操作"
            if "*" in policy_mod and not policy_mod["*"]:
                self._log_access(module, action, False, user, "模块全局策略拒绝")
                return False, "策略禁止此模块的所有操作"
            policy_global = self.policies.get("*", {})
            if action in policy_global and not policy_global[action]:
                self._log_access(module, action, False, user, "全局策略拒绝")
                return False, "全局策略禁止此操作"
            if "*" in policy_global and not policy_global["*"]:
                self._log_access(module, action, False, user, "全局默认策略拒绝")
                return False, "全局默认策略禁止操作"

        # 默认允许
        self._log_access(module, action, True, user)
        return True, ""

    def _log_access(self, module, action, allowed, user="system", reason=""):
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
        status = "✅允许" if allowed else "⛔拒绝"
        msg = f"[Security] {status} 用户:{user} {module}.{action}"
        if reason:
            msg += f" | 原因: {reason}"
        if allowed:
            self.logger.info(msg)
        else:
            self.logger.warning(msg)

    def add_policy(self, module: str, action: str, allowed: bool, persist: bool = True):
        with self.lock:
            if module not in self.policies:
                self.policies[module] = {}
            self.policies[module][action] = allowed
        if persist:
            self.save_policies()
        self.logger.info(f"更新策略: {module}.{action} = {'允许' if allowed else '禁止'}")

    def remove_policy(self, module: str, action: str):
        with self.lock:
            if module in self.policies and action in self.policies[module]:
                del self.policies[module][action]
                self.save_policies()
                self.logger.info(f"移除策略: {module}.{action}")

    def get_logs(self, max_entries: int = 100, filter_module: Optional[str] = None, filter_action: Optional[str] = None, filter_user: Optional[str] = None) -> List[dict]:
        with self.lock:
            logs = list(self.access_log)
        logs.reverse()
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

    def audit_trail(self, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[dict]:
        results = []
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    for line in f:
                        try:
                            # 可改为结构化日志解析
                            if "[Security]" in line:
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

# ==== 示例用法 ====
if __name__ == "__main__":
    security = SecurityManager(
        max_log_size=500,
        log_file="logs/security.log",
        policy_file="config/security_policy.json"
    )
    # 策略
    security.add_policy("payment", "process", True)
    security.add_policy("admin", "*", False)
    result, reason = security.check_access("payment", "process", user="customer123")
    print(f"支付处理: {'通过' if result else '拒绝'} - {reason}")
    result, reason = security.check_access("admin", "delete_user", user="hacker")
    print(f"删除用户: {'通过' if result else '拒绝'} - {reason}")
    # 日志
    print("\n最近5条日志:")
    for log in security.get_logs(max_entries=5):
        print(f"{log['timestamp']} | {log['user']} | {log['module']}.{log['action']} | {log['allowed']}")
    # 风控测试
    for _ in range(60):
        security.check_access("report", "generate", user="automation")
    result, reason = security.check_access("report", "generate", user="automation")
    print(f"\n报告生成: {'通过' if result else '拒绝'} - {reason}")
