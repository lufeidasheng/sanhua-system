import time
from core.system import system_sense, system_control
import daemon
import signal
import logging
import os
from core.core2_0.sanhuatongyu.logger import TraceLogger
log = TraceLogger(__name__)

LOG_FILE = '/tmp/main_controller.log'
RUNNING = True

def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def signal_handler(signum, frame):
    global RUNNING
    log.info(f"收到终止信号 {signum}，准备退出守护进程...")
    RUNNING = False

def main_loop(interval=60):
    global RUNNING
    while RUNNING:
        try:
            info = system_sense.get_system_health()
            log.info(f"系统状态: {info}")
            metrics = info.get('metrics') if isinstance(info, dict) else []
            metrics = metrics if isinstance(metrics, list) else []
            metrics_map = {
                str(item.get('name') or ''): str(item.get('value') or '')
                for item in metrics
                if isinstance(item, dict)
            }
            cpu_percent = float(metrics_map.get('CPU 使用率', '0').rstrip('%') or 0)
            memory_percent = float(metrics_map.get('内存 使用率', '0').rstrip('%') or 0)
            disk_percent = float(metrics_map.get('磁盘 使用率', '0').rstrip('%') or 0)

            if cpu_percent > 80:
                log.warning("⚠️ CPU占用过高，尝试重启网络...")
                result = system_control.restart_network()
                log.info(result)

            if memory_percent > 85:
                log.warning("⚠️ 内存占用过高，建议关闭一些程序")

            if disk_percent > 90:
                log.warning("⚠️ 磁盘空间不足，请清理磁盘")

        except Exception as e:
            log.error(f"运行时出错: {e}")

        time.sleep(interval)

if __name__ == "__main__":
    setup_logging()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    with daemon.DaemonContext():
        log.info("🟢 守护进程启动成功")
        main_loop()
        log.info("🛑 守护进程已退出")
