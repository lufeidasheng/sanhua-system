import time
import system_sense
import system_control
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
            info = system_sense.get_system_info()
            log.info(f"系统状态: {info}")

            if info.get('cpu_percent', 0) > 80:
                log.warning("⚠️ CPU占用过高，尝试重启网络...")
                result = system_control.restart_network()
                log.info(result)

            if info.get('memory_percent', 0) > 85:
                log.warning("⚠️ 内存占用过高，建议关闭一些程序")

            if info.get('disk_percent', 0) > 90:
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
