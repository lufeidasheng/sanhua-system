import multiprocessing as mp
import time
import logging
import signal
import os
import resource
import ctypes
import psutil
import json
import subprocess
from cryptography.fernet import Fernet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 企业级日志配置
def setup_enterprise_logger():
    logger = logging.getLogger("FedoraVoiceEntrySystem")
    logger.setLevel(logging.DEBUG)
    
    # 创建安全日志目录
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", "voice_entry")
    log_dir = os.path.abspath(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    os.chmod(log_dir, 0o700)
    
    # 设置SELinux安全上下文
    try:
        subprocess.run(["chcon", "-R", "-t", "voice_entry_log_t", log_dir], check=True)
        subprocess.run([
            "semanage", "fcontext", "-a", 
            "-t", "voice_entry_log_t", 
            f"'{log_dir}(/.*)?'"
        ], check=True)
    except Exception as e:
        logging.warning(f"SELinux日志上下文设置失败: {e}")
    
    # 文件处理器
    log_file = os.path.join(log_dir, f"voice_entry_{time.strftime('%Y%m%d')}.log")
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    os.chmod(log_file, 0o600)  # 设置日志文件权限
    
    # 系统日志处理器
    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    
    # 结构化日志格式
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d | %(name)s | %(levelname)s | %(process)d | '
        '%(threadName)s | %(module)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    fh.setFormatter(formatter)
    sh.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(sh)
    
    return logger

log = setup_enterprise_logger()

# 企业级配置管理
class EnterpriseConfig:
    """企业级安全配置管理"""
    CONFIG_PATH = "/etc/fedora_voice_entry/config.enc"
    KEY_PATH = "/etc/fedora_voice_entry/.config_key"
    
    @classmethod
    def generate_key(cls):
        """生成并安全存储加密密钥"""
        if not os.path.exists(os.path.dirname(cls.KEY_PATH)):
            os.makedirs(os.path.dirname(cls.KEY_PATH), 0o700)
            # 设置SELinux上下文
            try:
                subprocess.run(["chcon", "-t", "voice_entry_config_t", os.path.dirname(cls.KEY_PATH)], check=True)
            except Exception as e:
                log.warning(f"SELinux密钥目录上下文设置失败: {e}")
        
        if not os.path.exists(cls.KEY_PATH):
            key = Fernet.generate_key()
            with open(cls.KEY_PATH, 'wb') as f:
                f.write(key)
            os.chmod(cls.KEY_PATH, 0o400)
            log.info("生成新的配置加密密钥")
    
    @classmethod
    def get_key(cls):
        """获取加密密钥"""
        with open(cls.KEY_PATH, 'rb') as f:
            return f.read()
    
    @classmethod
    def load_config(cls):
        """加载并解密配置"""
        cls.generate_key()
        cipher = Fernet(cls.get_key())
        
        if os.path.exists(cls.CONFIG_PATH):
            with open(cls.CONFIG_PATH, 'rb') as f:
                encrypted = f.read()
            decrypted = cipher.decrypt(encrypted)
            return json.loads(decrypted.decode())
        else:
            log.warning("未找到配置文件，使用默认配置")
            return cls.default_config()
    
    @classmethod
    def save_config(cls, config):
        """加密并保存配置"""
        cipher = Fernet(cls.get_key())
        encrypted = cipher.encrypt(json.dumps(config).encode())
        
        os.makedirs(os.path.dirname(cls.CONFIG_PATH), exist_ok=True)
        with open(cls.CONFIG_PATH, 'wb') as f:
            f.write(encrypted)
        os.chmod(cls.CONFIG_PATH, 0o600)
        
        # 设置SELinux上下文
        try:
            subprocess.run(["chcon", "-t", "voice_entry_config_t", cls.CONFIG_PATH], check=True)
        except Exception as e:
            log.warning(f"SELinux配置文件上下文设置失败: {e}")
    
    @staticmethod
    def default_config():
        """默认企业级配置"""
        return {
            "voice_entry": {
                "monitor_interval": 5.0,
                "heartbeat_interval": 10.0,
                "max_restarts": 3,
                "realtime_priority": 90
            },
            "security": {
                "selinux_enforcement": "strict",
                "memory_protection": True,
                "cpu_affinity": "0-3"
            }
        }

# 实时性能优化
class RealtimeOptimizer:
    """实时性能优化工具类"""
    @staticmethod
    def set_realtime_priority(level=90):
        """设置实时优先级"""
        try:
            # 设置进程调度策略为实时
            os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(level))
            log.info(f"设置实时优先级: FIFO {level}")
        except PermissionError:
            log.warning("需要root权限或CAP_SYS_NICE能力设置实时优先级")
        except Exception as e:
            log.error(f"设置实时优先级失败: {e}")
    
    @staticmethod
    def lock_memory():
        """锁定内存防止交换"""
        try:
            # 锁定所有当前和未来的内存
            resource.setrlimit(resource.RLIMIT_MEMLOCK, 
                              (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
            
            # 使用mlockall锁定所有内存
            libc = ctypes.CDLL("libc.so.6")
            libc.mlockall(ctypes.c_int(0x2))  # MCL_FUTURE
            log.info("内存锁定成功 (mlockall)")
        except Exception as e:
            log.error(f"内存锁定失败: {e}")
    
    @staticmethod
    def pin_to_cpu(core_mask="0-3"):
        """将进程绑定到特定CPU核心"""
        try:
            if '-' in core_mask:
                # 格式 "0-3"
                start, end = map(int, core_mask.split('-'))
                affinity = list(range(start, end + 1))
            else:
                # 格式 "0,1,2,3"
                affinity = list(map(int, core_mask.split(',')))
            
            p = psutil.Process()
            p.cpu_affinity(affinity)
            log.info(f"CPU亲和性设置: {affinity}")
        except Exception as e:
            log.error(f"设置CPU亲和性失败: {e}")

# 配置热重载
class ConfigReloadHandler(FileSystemEventHandler):
    """配置文件热重载处理器"""
    def __init__(self, callback):
        self.callback = callback
        self.last_modified = 0
    
    def on_modified(self, event):
        if event.src_path == EnterpriseConfig.CONFIG_PATH:
            current_time = time.time()
            # 防止多次触发
            if current_time - self.last_modified > 2.0:
                self.last_modified = current_time
                log.info("检测到配置文件变更，重新加载配置")
                try:
                    self.callback()
                except Exception as e:
                    log.error(f"配置重载失败: {e}")

class VoiceEntryService:
    """企业级语音入口服务"""
    def __init__(self):
        self._running = False
        self._thread = None
        self._stop_event = mp.Event()
        self._config = None
        self._observer = None
        self._restart_count = 0
        self._last_heartbeat = time.monotonic()
        self._child_processes = []
        
        # 加载SELinux策略
        self.load_selinux_policy()
        
        # 应用实时优化
        self.apply_realtime_optimization()
        
        log.info("企业级语音入口服务初始化完成")

    def load_selinux_policy(self):
        """加载SELinux策略"""
        policy_path = "/usr/share/fedora_voice_entry/voice_entry_pro.te"
        if os.path.exists(policy_path):
            try:
                # 创建临时工作目录
                with tempfile.TemporaryDirectory() as tmpdir:
                    mod_path = os.path.join(tmpdir, "voice_entry_pro.mod")
                    pp_path = os.path.join(tmpdir, "voice_entry_pro.pp")
                    
                    subprocess.run([
                        "checkmodule", "-M", "-m", "-o", mod_path, policy_path
                    ], check=True)
                    subprocess.run([
                        "semodule_package", "-o", pp_path, 
                        "-m", mod_path
                    ], check=True)
                    subprocess.run(["semodule", "-i", pp_path], check=True)
                    log.info("SELinux策略加载成功")
            except Exception as e:
                log.error(f"SELinux策略加载失败: {e}")
    
    def apply_realtime_optimization(self):
        """应用实时性能优化"""
        # 设置实时优先级
        config = EnterpriseConfig.load_config()
        RealtimeOptimizer.set_realtime_priority(config["voice_entry"]["realtime_priority"])
        
        # 锁定内存
        if config["security"]["memory_protection"]:
            RealtimeOptimizer.lock_memory()
        
        # 设置CPU亲和性
        if config["security"]["cpu_affinity"]:
            RealtimeOptimizer.pin_to_cpu(config["security"]["cpu_affinity"])
    
    def load_config(self):
        """加载配置并设置热重载"""
        self._config = EnterpriseConfig.load_config()
        
        # 启动配置热重载
        if self._observer is None:
            self._observer = Observer()
            self._observer.schedule(
                ConfigReloadHandler(self.reload_config), 
                path=os.path.dirname(EnterpriseConfig.CONFIG_PATH)
            )
            self._observer.start()
            log.info("配置热重载监控已启动")
    
    def reload_config(self):
        """重新加载配置"""
        self._config = EnterpriseConfig.load_config()
        log.info("配置重新加载完成")
        
        # 重新应用实时优化
        self.apply_realtime_optimization()
    
    def send_heartbeat(self):
        """发送服务心跳"""
        current_time = time.monotonic()
        interval = self._config["voice_entry"]["heartbeat_interval"]
        
        if current_time - self._last_heartbeat > interval:
            log.info("❤️ 语音入口服务心跳")
            self._last_heartbeat = current_time
            return True
        return False
    
    def monitor_child_processes(self):
        """监控子进程状态"""
        for proc in self._child_processes[:]:
            if not proc.is_alive():
                exit_code = proc.exitcode
                log.warning(f"子进程 {proc.name} 异常退出，退出码: {exit_code}")
                self._child_processes.remove(proc)
                
                # 检查重启次数
                if self._restart_count < self._config["voice_entry"]["max_restarts"]:
                    log.info(f"重启子进程 {proc.name} ({self._restart_count + 1}/{self._config['voice_entry']['max_restarts']})")
                    new_proc = mp.Process(
                        target=proc._target,
                        args=proc._args,
                        kwargs=proc._kwargs,
                        name=proc.name,
                        daemon=True
                    )
                    new_proc.start()
                    self._child_processes.append(new_proc)
                    self._restart_count += 1
                else:
                    log.critical(f"子进程 {proc.name} 重启次数超过限制，系统将关闭")
                    self.stop()
    
    def start_child_process(self, target, name, args=(), kwargs={}):
        """启动子进程并监控"""
        proc = mp.Process(
            target=target,
            args=args,
            kwargs=kwargs,
            name=name,
            daemon=True
        )
        proc.start()
        self._child_processes.append(proc)
        log.info(f"启动子进程: {name} (PID: {proc.pid})")
    
    def _voice_entry_loop(self):
        """企业级语音入口主循环"""
        log.info("🎤 企业级语音入口服务启动")
        
        # 启动必要的子进程
        self.start_child_process(self.audio_capture, "AudioCapture")
        self.start_child_process(self.wake_word_detection, "WakeWordDetection")
        
        try:
            while self._running:
                try:
                    # 发送心跳
                    self.send_heartbeat()
                    
                    # 监控子进程状态
                    self.monitor_child_processes()
                    
                    # 主服务逻辑
                    log.debug("🎧 监控语音入口系统中...")
                    
                    # 检查系统资源
                    self.check_system_resources()
                    
                    time.sleep(self._config["voice_entry"]["monitor_interval"])
                except Exception as e:
                    log.error(f"语音入口主循环异常: {e}", exc_info=True)
                    time.sleep(1)
        finally:
            log.info("语音入口主循环结束")
    
    def audio_capture(self):
        """音频采集子进程"""
        # 设置实时优化
        config = EnterpriseConfig.load_config()
        RealtimeOptimizer.set_realtime_priority(config["voice_entry"]["realtime_priority"])
        
        log.info("🎤 专业音频采集启动")
        try:
            while not self._stop_event.is_set():
                # 模拟音频采集工作
                log.debug("采集音频数据...")
                time.sleep(1)
        except Exception as e:
            log.error(f"音频采集异常: {e}", exc_info=True)
        finally:
            log.info("音频采集停止")
    
    def wake_word_detection(self):
        """唤醒词检测子进程"""
        # 设置实时优化
        config = EnterpriseConfig.load_config()
        RealtimeOptimizer.set_realtime_priority(config["voice_entry"]["realtime_priority"])
        
        log.info("🔔 唤醒词检测启动")
        try:
            while not self._stop_event.is_set():
                # 模拟唤醒词检测工作
                log.debug("检测唤醒词...")
                time.sleep(2)
        except Exception as e:
            log.error(f"唤醒词检测异常: {e}", exc_info=True)
        finally:
            log.info("唤醒词检测停止")
    
    def check_system_resources(self):
        """检查系统资源使用情况"""
        try:
            # 内存使用
            mem = psutil.virtual_memory()
            if mem.percent > 90:
                log.warning(f"⚠️ 高内存使用: {mem.percent}%")
            
            # CPU负载
            cpu_load = psutil.getloadavg()[0] / os.cpu_count() * 100
            if cpu_load > 90:
                log.warning(f"⚠️ 高CPU负载: {cpu_load:.1f}%")
        except Exception as e:
            log.error(f"资源检查失败: {e}")

    def start(self):
        """启动企业级语音入口服务"""
        if self._running:
            log.warning("语音入口服务已启动，忽略重复启动")
            return
            
        self._running = True
        self._stop_event.clear()
        
        # 加载配置
        self.load_config()
        
        # 启动主线程
        self._thread = threading.Thread(target=self._voice_entry_loop, daemon=True)
        self._thread.start()
        
        log.info("🎤 企业级语音入口服务启动完成")

    def stop(self):
        """停止企业级语音入口服务"""
        if not self._running:
            return
            
        self._running = False
        self._stop_event.set()
        
        # 停止配置热重载
        if self._observer:
            self._observer.stop()
            self._observer.join()
        
        # 停止子进程
        for proc in self._child_processes:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)
                if proc.is_alive():
                    log.warning(f"强制终止子进程: {proc.name}")
                    proc.kill()
        
        # 等待主线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        
        log.info("🎤 企业级语音入口服务已停止")

# 服务管理函数
def start_service():
    """启动企业级语音入口服务"""
    service = VoiceEntryService()
    service.start()
    return service

def stop_service(service):
    """停止企业级语音入口服务"""
    service.stop()

# 主入口函数
def entry():
    log.info(f"✨ [{__name__}] 企业级语音入口服务启动中...")
    
    # 创建服务实例
    service = VoiceEntryService()
    
    # 注册信号处理
    def signal_handler(signum, frame):
        log.info(f"接收到信号 {signum}, 停止服务")
        service.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动服务
    service.start()
    
    # 等待服务停止
    try:
        while service._thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
    
    log.info("🎤 企业级语音入口服务运行结束")

def register_actions():
    """
    注册企业级动作接口
    """
    log.info(f"✅ [{__name__}] register_actions() 已调用，注册动作完成")
    # 这里可以注册服务启动/停止等动作

# 模块直接运行时启动服务
if __name__ == "__main__":
    # 设置进程名
    try:
        from setproctitle import setproctitle
        setproctitle("FedoraVoiceEntryService")
    except ImportError:
        pass
    
    # 企业级初始化
    if os.geteuid() == 0:
        log.warning("不建议以root权限运行，请使用专用系统用户")
    
    # 确保进程具有必要的能力
    try:
        # 设置实时能力
        subprocess.run(["setcap", "cap_sys_nice,cap_ipc_lock+eip", sys.executable])
    except Exception as e:
        log.warning(f"设置进程能力失败: {e}")
    
    entry()
