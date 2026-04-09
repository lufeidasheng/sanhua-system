"""
自学习模块（Fedora优化增强版）
优化点：
1. 增强Fedora系统兼容性
2. 改进线程安全机制
3. 优化滑动窗口计算效率
4. 添加Fedora性能监控集成
5. 增强配置验证
6. 完善事件处理流程
"""

import logging
import asyncio
import time
import os
import sys
import json
import psutil
from typing import Dict, Optional, List
from collections import deque
import threading

# 检测Fedora系统
IS_FEDORA = os.path.exists('/etc/fedora-release')

# 配置日志（默认INFO级别，调试时可改为DEBUG）
logger = logging.getLogger("self_learning_module")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        f"[%(asctime)s][{'Fedora' if IS_FEDORA else 'System'}][%(name)s][%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

__metadata__ = {
    "id": "self_learning_module",
    "name": "Fedora优化自学习模块",
    "version": "2.2",
    "dependencies": ["psutil"] if IS_FEDORA else [],
    "init": "init",
    "entry": "start",
    "events": ["task_completed", "system_feedback", "performance_alert"],
    "fedora_optimized": IS_FEDORA,
    "system_specific": {
        "fedora": {
            "tuned_parameters": ["response_delay", "priority_factor"],
            "recommended_config": {
                "window_size": 150,
                "adjustment_step": 0.03
            }
        }
    }
}


class SelfLearningCore:
    def __init__(self, initial_config: Optional[Dict] = None):
        # 使用更高效的锁机制
        self._lock = threading.RLock() if IS_FEDORA else threading.Lock()

        # 默认内核参数（Fedora系统有不同默认值）
        fedora_defaults = {
            "response_delay": 0.3 if IS_FEDORA else 0.5,
            "priority_factor": 1.2 if IS_FEDORA else 1.0,
            "retry_limit": 4 if IS_FEDORA else 3,
        }
        
        self.kernel_params = fedora_defaults.copy()

        # 默认学习配置（Fedora优化值）
        fedora_learning_config = {
            "response_time_threshold": 0.8,
            "adjustment_step": 0.03,
            "success_rate_target": 0.97,
            "history_size": 1500,
            "window_size": 150,
            "min_adjust_interval": 10,  # 最小调整间隔（秒）
        }
        
        self.learning_config = {
            "response_time_threshold": 1.0,
            "adjustment_step": 0.05,
            "success_rate_target": 0.95,
            "history_size": 1000,
            "window_size": 100,
            "min_adjust_interval": 15,
        }
        
        # 应用Fedora优化配置
        if IS_FEDORA:
            self.learning_config.update(fedora_learning_config)

        if initial_config:
            self.update_config(initial_config)

        # 统计数据
        self.task_stats = {
            "total_tasks": 0,
            "success_tasks": 0,
            "fail_tasks": 0,
            "avg_response_time": 0.0,
            "success_rate": 0.0,
        }

        # 优化滑动窗口结构
        self.window_stats = deque(maxlen=self.learning_config["window_size"])
        self.window_sum = 0.0
        self.window_successes = 0  # 单独跟踪成功次数提高效率

        # 任务历史（带时间戳）
        self.task_history = deque(maxlen=self.learning_config["history_size"])

        # 学习状态
        self.learning_state = {
            "last_adjustment": 0,
            "adjustment_count": 0,
            "last_trigger": None,
            "last_performance_check": 0,
        }

        # 性能指标
        self.performance_metrics = {
            "event_processing_time": 0.0,
            "event_count": 0,
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
        }
        
        # Fedora特定性能指标
        if IS_FEDORA:
            self.performance_metrics.update({
                "disk_io": 0.0,
                "network_io": 0.0,
            })

    def _update_performance_metrics(self):
        """更新系统性能指标"""
        try:
            self.performance_metrics["cpu_usage"] = psutil.cpu_percent(interval=0.1)
            self.performance_metrics["memory_usage"] = psutil.virtual_memory().percent
            
            if IS_FEDORA:
                disk_io = psutil.disk_io_counters()
                net_io = psutil.net_io_counters()
                self.performance_metrics["disk_io"] = disk_io.read_bytes + disk_io.write_bytes
                self.performance_metrics["network_io"] = net_io.bytes_sent + net_io.bytes_recv
                
        except Exception as e:
            logger.warning(f"更新性能指标失败: {e}")

    def update_task_stats(self, success: bool, response_time: float, task_type: str = "default"):
        """线程安全地更新任务统计及滑动窗口"""
        try:
            with self._lock:
                current_time = time.time()
                
                # 定期更新性能指标（最多每秒一次）
                if current_time - self.learning_state.get("last_performance_check", 0) > 1:
                    self._update_performance_metrics()
                    self.learning_state["last_performance_check"] = current_time
                
                # 更新全局统计
                self.task_stats["total_tasks"] += 1
                if success:
                    self.task_stats["success_tasks"] += 1
                else:
                    self.task_stats["fail_tasks"] += 1

                n = self.task_stats["total_tasks"]
                old_avg = self.task_stats["avg_response_time"]
                self.task_stats["avg_response_time"] = (old_avg * (n - 1) + response_time) / n
                self.task_stats["success_rate"] = (
                    self.task_stats["success_tasks"] / self.task_stats["total_tasks"] if n > 0 else 0.0
                )

                # 更新滑动窗口数据
                if len(self.window_stats) >= self.learning_config["window_size"]:
                    # 窗口已满，移除最旧元素
                    old_success, old_rt, _ = self.window_stats.popleft()
                    self.window_sum -= old_rt
                    if old_success:
                        self.window_successes -= 1
                
                # 添加新元素
                self.window_stats.append((success, response_time, task_type))
                self.window_sum += response_time
                if success:
                    self.window_successes += 1

                # 任务历史记录
                self.task_history.append({
                    "timestamp": current_time,
                    "success": success,
                    "response_time": response_time,
                    "task_type": task_type,
                    "system_load": self.performance_metrics["cpu_usage"]
                })

                logger.debug(f"统计更新: 总任务={self.task_stats['total_tasks']} 成功率={self.task_stats['success_rate']:.3f} "
                             f"窗口大小={len(self.window_stats)}")
        except Exception as e:
            logger.error(f"更新任务统计失败: {str(e)}", exc_info=True)

    def adjust_parameters(self) -> bool:
        """基于滑动窗口状态调整内核参数，返回是否做了调整"""
        try:
            with self._lock:
                current_time = time.time()
                window_size = len(self.window_stats)
                
                # 检查调整间隔
                min_interval = self.learning_config.get("min_adjust_interval", 10)
                if current_time - self.learning_state["last_adjustment"] < min_interval:
                    return False
                
                if window_size < 10:  # 窗口数据不足时不调整
                    return False

                window_avg_rt = self.window_sum / window_size
                window_success_rate = self.window_successes / window_size

                adjustments = []

                # 响应时间过长，减小延迟
                if window_avg_rt > self.learning_config["response_time_threshold"]:
                    old_delay = self.kernel_params["response_delay"]
                    # Fedora系统使用更激进的调整策略
                    step_factor = 1.5 if IS_FEDORA else 1.0
                    new_delay = max(0.1, old_delay - self.learning_config["adjustment_step"] * step_factor)
                    if new_delay != old_delay:
                        self.kernel_params["response_delay"] = new_delay
                        adjustments.append(f"响应延迟: {old_delay:.3f} -> {new_delay:.3f}")

                # 成功率不足，提高优先级因子
                if window_success_rate < self.learning_config["success_rate_target"]:
                    old_factor = self.kernel_params["priority_factor"]
                    step_factor = 1.2 if IS_FEDORA else 1.0
                    new_factor = min(2.5, old_factor + self.learning_config["adjustment_step"] * step_factor)
                    if new_factor != old_factor:
                        self.kernel_params["priority_factor"] = new_factor
                        adjustments.append(f"优先级因子: {old_factor:.3f} -> {new_factor:.3f}")

                # 成功率过高，适度降低优先级因子避免资源浪费
                elif window_success_rate > self.learning_config["success_rate_target"] + 0.05:
                    old_factor = self.kernel_params["priority_factor"]
                    new_factor = max(0.5, old_factor - self.learning_config["adjustment_step"] / 2)
                    if new_factor != old_factor:
                        self.kernel_params["priority_factor"] = new_factor
                        adjustments.append(f"优先级因子(降): {old_factor:.3f} -> {new_factor:.3f}")

                if adjustments:
                    self.learning_state["last_adjustment"] = current_time
                    self.learning_state["adjustment_count"] += 1
                    self.learning_state["last_trigger"] = "响应时间" if "响应延迟" in adjustments[0] else "成功率"
                    logger.info("参数调整: " + ", ".join(adjustments))
                    
                    # Fedora系统记录更详细的调整日志
                    if IS_FEDORA:
                        logger.debug(f"调整详情: 窗口大小={window_size} 平均响应={window_avg_rt:.3f}s 成功率={window_success_rate:.2%}")
                    
                    return True
                return False
        except Exception as e:
            logger.error(f"调整参数失败: {str(e)}", exc_info=True)
            return False

    def get_learning_status(self) -> Dict:
        """返回当前学习状态快照"""
        with self._lock:
            window_size = len(self.window_stats)
            window_avg_rt = self.window_sum / window_size if window_size > 0 else 0.0
            window_success_rate = self.window_successes / window_size if window_size > 0 else 0.0
            
            status = {
                "global_stats": self.task_stats.copy(),
                "window_stats": {
                    "size": window_size,
                    "avg_response_time": window_avg_rt,
                    "success_rate": window_success_rate,
                },
                "kernel_params": self.kernel_params.copy(),
                "learning_state": self.learning_state.copy(),
                "performance_metrics": self.performance_metrics.copy(),
                "task_history_count": len(self.task_history),
                "system_info": {
                    "os": "Fedora" if IS_FEDORA else "Unknown",
                    "optimized": IS_FEDORA
                }
            }
            
            # Fedora系统添加额外性能数据
            if IS_FEDORA:
                status["performance_metrics"].update({
                    "load_avg": os.getloadavg()[0],
                    "disk_usage": psutil.disk_usage('/').percent
                })
                
            return status

    def get_task_history(self, limit: int = 50) -> List[Dict]:
        """获取最近limit条任务历史"""
        with self._lock:
            return list(self.task_history)[-limit:]

    def reset_learning(self):
        """重置统计和学习状态（不重置配置）"""
        with self._lock:
            self.task_stats = {
                "total_tasks": 0,
                "success_tasks": 0,
                "fail_tasks": 0,
                "avg_response_time": 0.0,
                "success_rate": 0.0,
            }
            self.window_stats.clear()
            self.window_sum = 0.0
            self.window_successes = 0
            self.task_history.clear()
            self.learning_state = {
                "last_adjustment": time.time(),
                "adjustment_count": 0,
                "last_trigger": None,
                "last_performance_check": 0,
            }
            logger.info("学习状态已重置")

    def update_config(self, new_config: Dict):
        """更新学习配置，增强验证逻辑"""
        with self._lock:
            for key, value in new_config.items():
                if key not in self.learning_config:
                    logger.warning(f"尝试更新未知配置项: {key}")
                    continue

                # 验证配置值
                if key in ["response_time_threshold", "adjustment_step"]:
                    if not isinstance(value, (int, float)) or value <= 0:
                        logger.warning(f"无效的{key}值: {value} (必须为正数)")
                        continue
                        
                elif key in ["success_rate_target"]:
                    if not isinstance(value, (int, float)) or not (0 <= value <= 1):
                        logger.warning(f"无效的{key}值: {value} (必须在0-1之间)")
                        continue
                        
                elif key in ["history_size", "window_size", "min_adjust_interval"]:
                    if not isinstance(value, int) or value <= 0:
                        logger.warning(f"无效的{key}值: {value} (必须为正整数)")
                        continue
                    
                # 应用有效配置
                if key == "window_size":
                    # 创建新窗口并迁移数据
                    new_window = deque(maxlen=value)
                    # 迁移现有数据
                    for item in list(self.window_stats)[-value:]:
                        new_window.append(item)
                    self.window_stats = new_window
                    # 重新计算窗口统计
                    self.window_sum = sum(rt for _, rt, _ in self.window_stats)
                    self.window_successes = sum(1 for s, _, _ in self.window_stats if s)
                    self.learning_config[key] = value
                    logger.info(f"窗口大小调整为: {value}")
                    
                elif key == "history_size":
                    self.learning_config[key] = value
                    # 创建新历史队列
                    new_history = deque(maxlen=value)
                    # 迁移现有数据
                    for item in list(self.task_history)[-value:]:
                        new_history.append(item)
                    self.task_history = new_history
                    logger.info(f"历史记录大小调整为: {value}")
                    
                else:
                    self.learning_config[key] = value
                    logger.info(f"更新配置: {key} = {value}")
                    
                # Fedora系统特殊处理
                if IS_FEDORA and key == "adjustment_step":
                    logger.info("Fedora系统: 已应用优化调整步长")


# 创建单例核心对象
core = SelfLearningCore()


# ===== 模块生命周期函数 =====

async def init() -> bool:
    logger.info(f"{__metadata__['name']} v{__metadata__['version']} 初始化中...")
    # Fedora系统特殊初始化
    if IS_FEDORA:
        try:
            import psutil
            logger.info("Fedora系统: 已加载psutil进行性能监控")
        except ImportError:
            logger.warning("Fedora系统: 缺少psutil库，部分性能监控功能受限")
            # 回退到基本监控
            core.performance_metrics.pop("disk_io", None)
            core.performance_metrics.pop("network_io", None)
    
    await asyncio.sleep(0.1)
    logger.info(f"{__metadata__['name']} 初始化完成")
    return True


async def start(config: Optional[Dict] = None) -> Dict:
    logger.info("自学习模块启动")
    if config:
        core.update_config(config)
    
    # Fedora系统启动消息
    if IS_FEDORA:
        logger.info("Fedora优化模式已启用")
    
    return {
        "status": "success",
        "msg": "自学习模块已启动",
        "config": core.learning_config.copy(),
        "fedora_optimized": IS_FEDORA
    }


async def stop() -> bool:
    logger.info("自学习模块停止，释放资源")
    # 实现数据持久化
    try:
        # 保存关键状态（示例）
        status = core.get_learning_status()
        with open("learning_state.json", "w") as f:
            json.dump(status, f, indent=2)
        logger.info("学习状态已保存")
    except Exception as e:
        logger.error(f"保存状态失败: {e}")
    
    await asyncio.sleep(0.1)
    return True


# ===== 事件处理 =====

async def on_event(event_type: str, data: dict):
    start_time = time.perf_counter()
    try:
        logger.debug(f"接收事件: {event_type} 数据: {data}")
        if event_type == "task_completed":
            await handle_task_completed(data)
        elif event_type == "system_feedback":
            await handle_system_feedback(data)
        elif event_type == "performance_alert":
            await handle_performance_alert(data)
    except Exception as e:
        logger.error(f"事件处理异常 [{event_type}]: {str(e)}", exc_info=True)
    finally:
        process_time = time.perf_counter() - start_time
        with core._lock:
            old_avg = core.performance_metrics["event_processing_time"]
            count = core.performance_metrics["event_count"]
            core.performance_metrics["event_processing_time"] = (old_avg * count + process_time) / (count + 1)
            core.performance_metrics["event_count"] = count + 1


async def handle_task_completed(data: dict):
    task_name = data.get("task_name", "unknown_task")
    success = data.get("success", False)
    response_time = data.get("response_time", 0.5)

    core.update_task_stats(success, response_time, task_name)

    # 根据系统负载决定是否立即调整
    if core.performance_metrics["cpu_usage"] < 70:  # CPU低于70%时立即调整
        triggered = core.adjust_parameters()
        if triggered:
            logger.info(f"基于任务完成事件调整参数: {task_name}")
    else:
        logger.debug("CPU负载高，延迟参数调整")


async def handle_system_feedback(data: dict):
    feedback_type = data.get("type", "generic")
    message = data.get("message", "")

    logger.info(f"系统反馈: {feedback_type} - {message}")

    if feedback_type == "user_rating":
        rating = data.get("rating", 3)
        with core._lock:
            old_factor = core.kernel_params["priority_factor"]
            # Fedora系统使用更大的调整幅度
            adjustment_step = 0.15 if IS_FEDORA else 0.1
            if rating >= 4:
                new_factor = min(2.5, old_factor + adjustment_step)
            elif rating <= 2:
                new_factor = max(0.5, old_factor - adjustment_step)
            else:
                return
            core.kernel_params["priority_factor"] = new_factor
            logger.info(f"基于用户评分调整优先级因子: {old_factor:.3f} -> {new_factor:.3f}")

    elif feedback_type == "error_report":
        error_count = data.get("error_count", 1)
        with core._lock:
            old_retry = core.kernel_params["retry_limit"]
            # Fedora系统允许更高的重试次数
            max_retry = 7 if IS_FEDORA else 5
            core.kernel_params["retry_limit"] = min(max_retry, max(1, old_retry + error_count))
            logger.info(f"更新重试限制: {old_retry} -> {core.kernel_params['retry_limit']}")


async def handle_performance_alert(data: dict):
    alert_type = data.get("alert_type", "generic")
    metric = data.get("metric", {})

    logger.warning(f"性能警报: {alert_type}")
    logger.debug(f"警报详情: {json.dumps(metric, indent=2, ensure_ascii=False)}")

    if alert_type == "high_cpu":
        with core._lock:
            old_delay = core.kernel_params["response_delay"]
            # Fedora系统使用更保守的调整策略
            reduction = 0.15 if IS_FEDORA else 0.2
            new_delay = max(0.1, old_delay * (1 + reduction))  # 增加延迟而不是减少
            if new_delay != old_delay:
                core.kernel_params["response_delay"] = new_delay
                logger.info(f"CPU过高警报响应，调整响应延迟: {old_delay:.3f} -> {new_delay:.3f}")


# ===== 外部接口 =====

async def query_status() -> Dict:
    logger.info("查询自学习模块状态")
    return core.get_learning_status()


async def get_recent_history(limit: int = 20) -> List[Dict]:
    logger.info(f"获取最近{limit}条任务历史")
    return core.get_task_history(limit)


async def reset_learning_state() -> Dict:
    logger.warning("重置学习状态")
    core.reset_learning()
    return {"status": "success", "msg": "学习状态已重置"}


async def update_learning_config(new_config: Dict) -> Dict:
    """更新学习配置"""
    logger.info(f"更新学习配置: {new_config}")
    core.update_config(new_config)
    return {"status": "success", "config": core.learning_config.copy()}


async def get_kernel_params() -> Dict:
    """获取当前内核参数"""
    return core.kernel_params.copy()


def register_actions(dispatcher):
    """
    注册模块动作接口。
    通过 dispatcher.register_action 注册关键词与回调函数绑定。
    """
    # 注册查询状态动作
    dispatcher.register_action(
        "查询学习状态",
        query_status,
        module_name="modules.self_learning_module"
    )
    
    # 注册重置学习状态动作
    dispatcher.register_action(
        "重置学习",
        reset_learning_state,
        module_name="modules.self_learning_module"
    )
    
    # 注册获取内核参数动作
    dispatcher.register_action(
        "获取学习参数",
        get_kernel_params,
        module_name="modules.self_learning_module"
    )
    
    # Fedora系统专用动作
    if IS_FEDORA:
        dispatcher.register_action(
            "Fedora学习状态",
            query_status,
            module_name="modules.self_learning_module"
        )
