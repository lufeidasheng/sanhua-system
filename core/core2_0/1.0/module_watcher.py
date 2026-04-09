import os
import sys
import importlib
import logging
import threading
import hashlib
import traceback
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from threading import Timer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("module_watcher.log")
    ]
)
logger = logging.getLogger("ModuleWatcher")

MODULES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules"))

class ModuleWatcher(FileSystemEventHandler):
    """增强型模块热重载管理器"""
    
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.module_map = {}  # 模块名 -> module对象
        self.module_status = {}  # 模块状态追踪
        self.module_hashes = {}  # 模块文件哈希值
        self.reload_timers = {}  # 重载防抖定时器
        self.lock = threading.Lock()
        self.load_initial_modules()

    def load_initial_modules(self):
        """启动时加载所有现有模块"""
        logger.info("初始化加载模块...")
        for fname in os.listdir(MODULES_DIR):
            if fname.endswith(".py") and not fname.startswith("_"):
                filepath = os.path.join(MODULES_DIR, fname)
                self._load_module(filepath)
        logger.info(f"初始模块加载完成: {len(self.module_map)}个模块")

    def on_created(self, event):
        """处理文件创建事件"""
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        logger.info(f"检测到新模块: {event.src_path}")
        self._load_module(event.src_path)

    def on_modified(self, event):
        """处理文件修改事件 - 带防抖"""
        if event.is_directory or not event.src_path.endswith(".py"):
            return
            
        module_name = self._get_module_name(event.src_path)
        
        # 计算文件哈希检查是否真实修改
        current_hash = self._file_hash(event.src_path)
        if module_name in self.module_hashes and self.module_hashes[module_name] == current_hash:
            logger.debug(f"文件 {event.src_path} 内容未变化，跳过重载")
            return
        
        # 防抖处理 - 1秒内多次修改只重载一次
        if module_name in self.reload_timers:
            self.reload_timers[module_name].cancel()
            
        logger.info(f"检测到模块修改: {event.src_path}")
        self.reload_timers[module_name] = Timer(1.0, self._reload_module, [event.src_path])
        self.reload_timers[module_name].start()

    def on_deleted(self, event):
        """处理文件删除事件"""
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        logger.warning(f"检测到模块删除: {event.src_path}")
        self._unload_module(event.src_path)

    def _get_module_name(self, filepath):
        """从文件路径生成模块名"""
        rel_path = os.path.relpath(filepath, MODULES_DIR)
        module_name = rel_path.replace(".py", "").replace(os.sep, ".")
        return f"modules.{module_name}"

    def _file_hash(self, filepath):
        """计算文件哈希值"""
        with open(filepath, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _security_scan(self, filepath):
        """基本安全扫描"""
        try:
            with open(filepath, "r") as f:
                content = f.read()
                dangerous_patterns = [
                    "__import__", "eval(", "exec(", "open(",
                    "os.system", "subprocess.run", "shutil."
                ]
                
                for pattern in dangerous_patterns:
                    if pattern in content:
                        logger.warning(f"安全警告: 检测到危险操作 '{pattern}' in {filepath}")
                        return False
            return True
        except Exception as e:
            logger.error(f"安全扫描失败: {str(e)}")
            return False

    def _load_module(self, filepath):
        """加载新模块"""
        if not self._security_scan(filepath):
            logger.error(f"安全扫描未通过: {filepath}")
            return
            
        module_name = self._get_module_name(filepath)
        with self.lock:
            if module_name in self.module_map:
                logger.info(f"模块 {module_name} 已存在，尝试重新加载")
                self._reload_module(filepath)
                return
                
            try:
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # 执行注册
                self._register_module(module_name, module)
                
                # 更新状态
                self.module_map[module_name] = module
                self.module_status[module_name] = "loaded"
                self.module_hashes[module_name] = self._file_hash(filepath)
                
                logger.info(f"✅ 成功加载模块: {module_name}")
            except Exception as e:
                logger.error(f"加载模块失败: {module_name}")
                logger.error(traceback.format_exc())
                self.module_status[module_name] = f"error: {str(e)}"

    def _reload_module(self, filepath):
        """重新加载模块"""
        module_name = self._get_module_name(filepath)
        with self.lock:
            try:
                # 清理旧模块
                if module_name in self.module_map:
                    self._unregister_module(module_name)
                
                # 重新加载
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    spec = importlib.util.spec_from_file_location(module_name, filepath)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                
                # 重新注册
                self._register_module(module_name, module)
                
                # 更新状态
                self.module_map[module_name] = module
                self.module_status[module_name] = "reloaded"
                self.module_hashes[module_name] = self._file_hash(filepath)
                
                logger.info(f"🔄 成功重载模块: {module_name}")
            except Exception as e:
                logger.error(f"重载模块失败: {module_name}")
                logger.error(traceback.format_exc())
                self.module_status[module_name] = f"reload_error: {str(e)}"
                # 尝试恢复旧版本
                if module_name in self.module_map:
                    try:
                        self._register_module(module_name, self.module_map[module_name])
                        logger.warning(f"已恢复模块旧版本: {module_name}")
                    except:
                        logger.error("恢复模块失败!")

    def _unload_module(self, filepath):
        """卸载模块"""
        module_name = self._get_module_name(filepath)
        with self.lock:
            if module_name in self.module_map:
                try:
                    # 清理注册
                    self._unregister_module(module_name)
                    
                    # 清理引用
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                    
                    # 移除跟踪
                    self.module_map.pop(module_name, None)
                    self.module_status.pop(module_name, None)
                    self.module_hashes.pop(module_name, None)
                    
                    logger.info(f"🗑️ 已卸载模块: {module_name}")
                except Exception as e:
                    logger.error(f"卸载模块失败: {str(e)}")
                    self.module_status[module_name] = f"unload_error: {str(e)}"

    def _register_module(self, module_name, module):
        """执行模块注册"""
        if hasattr(module, "register_actions"):
            try:
                # 记录注册前的动作数量
                pre_count = len(self.dispatcher.get_actions()) if hasattr(self.dispatcher, "get_actions") else 0
                
                # 执行注册
                module.register_actions(self.dispatcher)
                
                # 记录注册后的变化
                if hasattr(self.dispatcher, "get_actions"):
                    new_count = len(self.dispatcher.get_actions())
                    logger.info(f"注册动作: {module_name} 添加了 {new_count - pre_count} 个新动作")
            except Exception as e:
                logger.error(f"注册动作失败: {str(e)}")
                raise

    def _unregister_module(self, module_name):
        """清理模块注册"""
        if hasattr(self.dispatcher, "clear_actions_by_module"):
            try:
                # 记录清理前的动作数量
                pre_count = len(self.dispatcher.get_actions()) if hasattr(self.dispatcher, "get_actions") else 0
                
                # 执行清理
                self.dispatcher.clear_actions_by_module(module_name)
                
                # 记录清理后的变化
                if hasattr(self.dispatcher, "get_actions"):
                    new_count = len(self.dispatcher.get_actions())
                    logger.info(f"清理动作: {module_name} 移除了 {pre_count - new_count} 个动作")
            except Exception as e:
                logger.error(f"清理动作失败: {str(e)}")
                raise

    def get_module_status(self):
        """获取所有模块状态"""
        return self.module_status.copy()

def start_module_watcher(dispatcher):
    """启动模块监控系统"""
    logger.info(f"启动模块监控: {MODULES_DIR}")
    
    observer = Observer()
    event_handler = ModuleWatcher(dispatcher)
    
    observer.schedule(event_handler, path=MODULES_DIR, recursive=True)
    observer.start()
    
    logger.info("模块监控已启动")
    return observer, event_handler

# 使用示例
if __name__ == "__main__":
    # 模拟调度器
    class MockDispatcher:
        def __init__(self):
            self.actions = {}
            
        def register_action(self, name, action):
            self.actions[name] = action
            
        def clear_actions_by_module(self, module_name):
            to_remove = [name for name, action in self.actions.items() 
                        if getattr(action, "__module__", "") == module_name]
            for name in to_remove:
                self.actions.pop(name)
                
        def get_actions(self):
            return self.actions
    
    dispatcher = MockDispatcher()
    observer, watcher = start_module_watcher(dispatcher)
    
    try:
        while True:
            # 保持主线程运行
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
