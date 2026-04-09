import time
import threading
import os
from typing import Optional, Dict, Any

from .context import SystemContext
from .module.manager import ModuleManager
from .system_module import SystemModule
from .module.meta import ModuleMeta
from .logger import get_logger, configure_logging

# ==== 🧠 AI中枢核心（聚核助手/三花聚顶AICore） ====
from core.aicore.aicore import AICore  # 路径根据你实际aicore存放处调整
from core.core2_0.sanhuatongyu.action_manager import ActionManager  # 新增动作分发器

class SanHuaTongYu:
    """
    三花统御系统核心 (全生命周期主控器)
    - 系统生命周期管理、模块加载/卸载、健康监控、资源清理
    - 集成AI中枢（AICore）为全局智能助手
    - 统一动作分发（ActionManager）
    """
    VERSION = '3.0.0'

    def __init__(
        self,
        modules_dir: str,
        global_config_path: str,
        user_config_path: str,
        dev_mode: bool = False,
        health_check_interval: int = 30
    ) -> None:
        # ===== 日志系统全局配置 =====
        configure_logging(
            level="INFO",
            log_dir="logs",
            json_format=True,
            i18n_lang="zh_CN"
        )
        self.logger = get_logger("core")

        # ====== 参数校验 ======
        if not os.path.isdir(modules_dir):
            self.logger.critical("invalid_modules_dir", extra_data={"dir": modules_dir})
            raise ValueError(f"模块目录无效: {modules_dir}")
        if not os.path.isfile(global_config_path):
            self.logger.critical("global_config_missing", extra_data={"file": global_config_path})
            raise ValueError(f"全局配置文件不存在: {global_config_path}")
        if health_check_interval <= 0:
            self.logger.critical("invalid_health_interval", extra_data={"interval": health_check_interval})
            raise ValueError("健康检查间隔必须大于0")

        self._lock = threading.Lock()
        self._health_report_thread: Optional[threading.Thread] = None
        self._running = False
        self._shutting_down = False
        self.health_check_interval = health_check_interval

        # ====== 核心对象 ======
        self.context = SystemContext(global_config_path, user_config_path, dev_mode)
        self.module_manager = ModuleManager(modules_dir, self.context)
        self.context.module_manager = self.module_manager

        # === 集成 AICore 智能中枢 ===
        self.aicore = AICore()
        self.logger.info("AICore AI模块已集成到主控")

        # === ActionManager 能力总线 ===
        self.action_manager = ActionManager(self.context)
        # ——统一注册 AICore 动作（命名空间统一，支持批量注册/自动发现）——
        self.action_manager.register_action(
            name="aicore.chat",
            func=self.aicore.chat,
            description="AI 智能对话",
            permission="user",
            module="aicore"
        )
        # 如果 aicore 有更多自定义动作，批量注册如下：
        # for act in self.aicore.get_all_actions(): self.action_manager.register_action(...)

        self.logger.info("system_start", extra_data={
            "version": self.VERSION,
            "mode": "开发" if dev_mode else "生产"
        })

        # 系统初始化事件通知
        if self.event_bus_ready:
            self.context.event_bus.publish('SYSTEM_INIT', {'version': self.VERSION})

    @property
    def event_bus_ready(self) -> bool:
        """事件总线就绪检测"""
        return bool(self.context.event_bus and self.context.event_bus.is_ready())

    def __enter__(self) -> 'SanHuaTongYu':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.shutdown()
        if exc_type:
            self.logger.error("context_exit_with_error", exc=exc_val)
        return False

    def load_system_module(self) -> None:
        """加载内置系统核心模块"""
        system_meta = ModuleMeta(
            name='system_core',
            path='',
            manifest={
                'name': 'system_core',
                'version': self.VERSION,
                'visibility': 'core',
                'description': '三花统御系统核心服务'
            }
        )
        with self._lock:
            system_mod = SystemModule(system_meta, self.context)
            self.module_manager.loaded_modules['system_core'] = system_mod
        try:
            system_mod.preload()
            system_mod.setup()
        except Exception as e:
            self.logger.error("system_module_load_failed", exc=e)
            raise RuntimeError(f"系统模块加载失败: {str(e)}")

    def run(self, entry_point: str = 'cli') -> None:
        if self._running:
            self.logger.warning("system_already_running")
            return
        try:
            self.load_system_module()
            self.module_manager.load_modules_metadata()
            self.module_manager.load_modules(entry_point)
            with self._lock:
                if self._running:
                    return
                self.context.system_running = True
                self.module_manager.start_modules()
                self._running = True
                self._shutting_down = False
                # 启动健康检查线程
                self._health_report_thread = threading.Thread(
                    target=self._health_report_loop,
                    name="HealthReporter",
                    daemon=False
                )
                self._health_report_thread.start()
            self.logger.info("system_started")
            # 主循环
            while self._running:
                try:
                    time.sleep(1)
                except KeyboardInterrupt:
                    self.logger.info("keyboard_interrupt_received")
                    self.shutdown()
                    break
        except KeyboardInterrupt:
            self.logger.info("keyboard_interrupt_received")
            self.shutdown()
        except Exception as e:
            self.logger.critical("system_run_failed", exc=e)
            self.shutdown()
            raise RuntimeError(f"系统启动失败: {str(e)}")

    def _health_report_loop(self) -> None:
        while self._running:
            try:
                time.sleep(self.health_check_interval)
                health = self.module_manager.health_check()
                if health['status'] != 'OK':
                    self.logger.warning("health_check_warning", extra_data={"status": health['status']})
                if self.event_bus_ready:
                    self.context.event_bus.publish('HEALTH_REPORT', health)
            except Exception as e:
                self.logger.error("health_check_failed", exc=e)
                if not self._running:
                    break

    # === 全局AI接口暴露 ===
    def ask_ai(self, query: str) -> str:
        """统一AI接口，其他模块和CLI都能直接调用"""
        # 推荐所有入口通过 ActionManager 分发，不直接 self.aicore.chat
        return self.action_manager.call_action("aicore.chat", query)

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._shutting_down = True
            self.context.system_running = False
        try:
            self.module_manager.stop_modules()
            self.logger.info("modules_stopped")
        except Exception as e:
            self.logger.error("module_stop_failed", exc=e)
        if self._health_report_thread and self._health_report_thread.is_alive():
            try:
                self._health_report_thread.join(timeout=5)
                if self._health_report_thread.is_alive():
                    self.logger.warning("health_thread_still_running")
            except KeyboardInterrupt:
                self.logger.warning("用户中断，健康线程强制结束")
            except Exception as e:
                self.logger.error("health_thread_join_failed", exc=e)
        try:
            self.context.cleanup()
            self.logger.info("context_cleaned")
        except Exception as e:
            self.logger.error("context_cleanup_failed", exc=e)
        # ========== 关闭AICore ==========
        if hasattr(self, 'aicore') and self.aicore:
            self.aicore.shutdown()
            self.logger.info("AICore已关闭")
        self.logger.info("system_stopped")

    def restart(self) -> None:
        self.logger.info("system_restarting")
        self.shutdown()
        self.run()

    def get_uptime(self) -> float:
        return time.time() - self.context.start_time

    @property
    def is_running(self) -> bool:
        return self._running

# ==== 🦄 示例：主控与AI一体化交互 ====
if __name__ == "__main__":
    system = SanHuaTongYu(
        modules_dir="modules",
        global_config_path="conf/global.yaml",
        user_config_path="conf/user.yaml",
        dev_mode=True,
        health_check_interval=30
    )
    system.run()
    # 推荐所有能力都用 ActionManager 分发
    print(system.ask_ai("三花聚顶是什么？"))
    # 你也可以这样直接调用：
    print(system.action_manager.call_action("aicore.chat", "你好聚顶！"))
    # 主控关闭后，AI资源自动释放
    system.shutdown()
