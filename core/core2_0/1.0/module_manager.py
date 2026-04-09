import importlib
import logging
import threading
import sys
import traceback
import time  # 添加缺失的time模块导入
from types import ModuleType
from typing import Dict, Callable, Any, List, Optional, Set

# 配置高级日志
logger = logging.getLogger("ModuleManager")
logger.setLevel(logging.DEBUG)  # 使用DEBUG级别以获取更多信息

# 添加格式化处理器
if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器
    file_handler = logging.FileHandler("module_manager.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

class ModuleManager:
    """高级模块管理器，支持热重载和依赖管理"""
    
    def __init__(self, dispatcher):
        """
        初始化模块管理器
        
        Args:
            dispatcher: 动作分发器实例，需实现 register_action 和 clear_actions_by_module 方法
        """
        self.dispatcher = dispatcher
        self.module_map: Dict[str, ModuleType] = {}  # 模块名 -> 模块对象
        self.module_dependencies: Dict[str, List[str]] = {}  # 模块依赖关系
        self.reverse_dependencies: Dict[str, Set[str]] = {}  # 反向依赖关系
        self.lock = threading.RLock()  # 可重入锁，支持嵌套调用
        self.module_metadata: Dict[str, dict] = {}  # 模块元数据
        self.load_order: List[str] = []  # 模块加载顺序
        
        # 注册默认模块方法
        self.register_module_method("register_actions", self._default_register_actions)
        self.register_module_method("initialize", self._default_initialize)
        self.register_module_method("cleanup", self._default_cleanup)
    
    def register_module_method(self, method_name: str, default_impl: Callable):
        """注册模块方法及其默认实现"""
        # 修复闭包问题：使用默认参数绑定当前值
        def create_wrapper(default):
            return lambda m, *a, **k: (
                getattr(m, method_name, lambda *_, **__: None)(*a, **k) 
                if hasattr(m, method_name) 
                else default(m, *a, **k)
            )
        
        setattr(self, f"_default_{method_name}", default_impl)
        setattr(self, f"_call_{method_name}", create_wrapper(default_impl))
    
    def _default_register_actions(self, module: ModuleType, module_name: str):
        """默认动作注册实现"""
        if not hasattr(module, "register_actions"):
            logger.warning(f"模块 {module_name} 缺少 register_actions 方法")
    
    def _default_initialize(self, module: ModuleType, module_name: str):
        """默认模块初始化实现"""
        return True
    
    def _default_cleanup(self, module: ModuleType, module_name: str):
        """默认模块清理实现"""
        return True
    
    def _update_reverse_dependencies(self, module_name: str, dependencies: List[str]):
        """更新反向依赖关系"""
        # 清除旧的依赖关系
        for dep in self.module_dependencies.get(module_name, []):
            if module_name in self.reverse_dependencies.get(dep, set()):
                self.reverse_dependencies[dep].remove(module_name)
        
        # 添加新的依赖关系
        for dep in dependencies:
            if dep not in self.reverse_dependencies:
                self.reverse_dependencies[dep] = set()
            self.reverse_dependencies[dep].add(module_name)
    
    def load_module(self, module_name: str, dependencies: Optional[List[str]] = None) -> bool:
        """
        加载指定模块
        
        Args:
            module_name: 要加载的模块名
            dependencies: 该模块依赖的其他模块列表
            
        Returns:
            bool: 加载是否成功
        """
        with self.lock:
            # 检查是否已加载
            if module_name in self.module_map:
                logger.info(f"模块 {module_name} 已加载，尝试重新加载")
                return self.reload_module(module_name)
            
            # 解析依赖关系
            dependencies = dependencies or []
            self.module_dependencies[module_name] = dependencies
            self._update_reverse_dependencies(module_name, dependencies)
            
            # 加载依赖模块
            for dep in dependencies:
                if dep not in self.module_map:
                    logger.info(f"加载 {module_name} 的依赖模块: {dep}")
                    if not self.load_module(dep):
                        logger.error(f"依赖模块 {dep} 加载失败，无法加载 {module_name}")
                        # 回滚：移除依赖关系
                        self.module_dependencies.pop(module_name, None)
                        self._update_reverse_dependencies(module_name, [])
                        return False
            
            try:
                # 动态导入模块
                logger.debug(f"开始导入模块: {module_name}")
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)
                
                # 执行模块初始化
                if not self._call_initialize(module, module_name):
                    logger.error(f"模块 {module_name} 初始化失败")
                    return False
                
                # 注册模块动作
                self._call_register_actions(module, module_name)
                
                # 存储模块引用
                self.module_map[module_name] = module
                self.module_metadata[module_name] = {
                    "load_time": time.time(),
                    "version": getattr(module, "__version__", "unknown"),
                    "dependencies": dependencies.copy(),
                    "load_count": 1
                }
                self.load_order.append(module_name)
                
                logger.info(f"成功加载模块: {module_name} (版本: {self.module_metadata[module_name]['version']})")
                return True
            except ImportError as ie:
                logger.error(f"导入模块 {module_name} 失败: {str(ie)}")
            except Exception as e:
                logger.error(f"加载模块 {module_name} 时发生错误: {str(e)}")
                logger.debug(traceback.format_exc())
                # 清理部分状态
                if module_name in self.module_map:
                    del self.module_map[module_name]
                if module_name in self.module_metadata:
                    del self.module_metadata[module_name]
                self.module_dependencies.pop(module_name, None)
                self._update_reverse_dependencies(module_name, [])
            return False
    
    def reload_module(self, module_name: str) -> bool:
        """
        重新加载指定模块
        
        Args:
            module_name: 要重新加载的模块名
            
        Returns:
            bool: 重载是否成功
        """
        with self.lock:
            if module_name not in self.module_map:
                logger.warning(f"尝试重新加载未加载的模块: {module_name}")
                return self.load_module(module_name)
            
            try:
                module = self.module_map[module_name]
                
                # 执行清理操作
                if not self._call_cleanup(module, module_name):
                    logger.warning(f"模块 {module_name} 清理过程中出现问题")
                
                # 清理旧动作
                if hasattr(self.dispatcher, "clear_actions_by_module"):
                    self.dispatcher.clear_actions_by_module(module_name)
                
                # 重新加载模块
                logger.debug(f"开始重新加载模块: {module_name}")
                module = importlib.reload(module)
                self.module_map[module_name] = module
                
                # 更新元数据
                metadata = self.module_metadata[module_name]
                metadata.update({
                    "reload_time": time.time(),
                    "reload_count": metadata.get("reload_count", 0) + 1,
                    "last_load_time": time.time(),
                    "version": getattr(module, "__version__", metadata.get("version", "unknown"))
                })
                
                # 重新初始化
                if not self._call_initialize(module, module_name):
                    logger.error(f"模块 {module_name} 重新初始化失败")
                    return False
                
                # 重新注册动作
                self._call_register_actions(module, module_name)
                
                logger.info(f"成功重新加载模块: {module_name}")
                
                # 检查依赖此模块的其他模块
                self._check_dependent_modules(module_name)
                
                return True
            except Exception as e:
                logger.error(f"重新加载模块 {module_name} 失败: {str(e)}")
                logger.debug(traceback.format_exc())
                # 尝试恢复：重新加载旧模块
                if module_name in sys.modules:
                    logger.warning(f"尝试恢复模块 {module_name} 的旧版本")
                    try:
                        self.module_map[module_name] = importlib.reload(sys.modules[module_name])
                        # 重新初始化
                        self._call_initialize(self.module_map[module_name], module_name)
                        self._call_register_actions(self.module_map[module_name], module_name)
                        return False
                    except Exception as e2:
                        logger.error(f"恢复模块 {module_name} 失败: {str(e2)}")
                        # 无法恢复，卸载模块
                        self.unload_module(module_name)
                return False
    
    def _check_dependent_modules(self, module_name: str):
        """检查依赖此模块的其他模块"""
        dependents = self.reverse_dependencies.get(module_name, set())
        if dependents:
            logger.warning(f"以下模块依赖已更改的模块 {module_name}，建议重新加载: {', '.join(dependents)}")
    
    def unload_module(self, module_name: str) -> bool:
        """
        卸载指定模块
        
        Args:
            module_name: 要卸载的模块名
            
        Returns:
            bool: 卸载是否成功
        """
        with self.lock:
            if module_name not in self.module_map:
                logger.warning(f"尝试卸载未加载的模块: {module_name}")
                return False
            
            # 检查是否有其他模块依赖此模块
            dependents = self.reverse_dependencies.get(module_name, set())
            if dependents:
                logger.error(f"无法卸载模块 {module_name}，以下模块依赖它: {', '.join(dependents)}")
                return False
            
            try:
                module = self.module_map[module_name]
                
                # 执行清理操作
                if not self._call_cleanup(module, module_name):
                    logger.warning(f"模块 {module_name} 清理过程中出现问题")
                
                # 清理动作
                if hasattr(self.dispatcher, "clear_actions_by_module"):
                    self.dispatcher.clear_actions_by_module(module_name)
                
                # 从内存中移除
                del self.module_map[module_name]
                if module_name in sys.modules:
                    del sys.modules[module_name]
                
                # 清理元数据和依赖关系
                self.module_metadata.pop(module_name, None)
                self.module_dependencies.pop(module_name, None)
                self._update_reverse_dependencies(module_name, [])
                
                # 从加载顺序中移除
                if module_name in self.load_order:
                    self.load_order.remove(module_name)
                
                logger.info(f"成功卸载模块: {module_name}")
                return True
            except Exception as e:
                logger.error(f"卸载模块 {module_name} 失败: {str(e)}")
                logger.debug(traceback.format_exc())
                return False
    
    def list_modules(self) -> List[str]:
        """获取所有已加载模块列表"""
        with self.lock:
            return list(self.module_map.keys())
    
    def get_module(self, module_name: str) -> Optional[ModuleType]:
        """获取指定模块对象"""
        with self.lock:
            return self.module_map.get(module_name)
    
    def get_module_metadata(self, module_name: str) -> dict:
        """获取模块元数据"""
        with self.lock:
            return self.module_metadata.get(module_name, {}).copy()
    
    def get_dependencies(self, module_name: str) -> List[str]:
        """获取模块依赖"""
        with self.lock:
            return self.module_dependencies.get(module_name, []).copy()
    
    def get_dependents(self, module_name: str) -> List[str]:
        """获取依赖此模块的模块列表"""
        with self.lock:
            return list(self.reverse_dependencies.get(module_name, set()).copy())
    
    def shutdown(self):
        """关闭所有模块并清理资源"""
        with self.lock:
            # 按照加载顺序的逆序卸载（后加载的先卸载）
            unload_order = self.load_order[::-1]
            logger.info(f"开始卸载所有模块，顺序: {unload_order}")
            
            for module_name in unload_order[:]:  # 使用副本进行迭代
                if module_name in self.module_map:
                    try:
                        logger.debug(f"正在卸载模块: {module_name}")
                        self.unload_module(module_name)
                    except Exception as e:
                        logger.error(f"卸载模块 {module_name} 时出错: {str(e)}")
            
            logger.info("所有模块已卸载，模块管理器关闭")

# 示例用法
if __name__ == "__main__":
    # 创建一个模拟分发器
    class MockDispatcher:
        def __init__(self):
            self.actions = {}
        
        def register_action(self, action_name, action_func, module_name):
            self.actions[action_name] = (action_func, module_name)
            print(f"注册动作: {action_name} from {module_name}")
        
        def clear_actions_by_module(self, module_name):
            to_remove = [k for k, v in self.actions.items() if v[1] == module_name]
            for k in to_remove:
                del self.actions[k]
            print(f"清理 {module_name} 的动作: {len(to_remove)} 个")
    
    # 创建模块管理器
    dispatcher = MockDispatcher()
    manager = ModuleManager(dispatcher)
    
    # 加载模块
    manager.load_module("math", dependencies=[])
    manager.load_module("datetime", dependencies=[])
    
    # 获取模块信息
    print("已加载模块:", manager.list_modules())
    print("math 模块元数据:", manager.get_module_metadata("math"))
    print("datetime 依赖项:", manager.get_dependencies("datetime"))
    
    # 重新加载模块
    manager.reload_module("math")
    
    # 尝试卸载有依赖的模块
    print("尝试卸载math模块:", "成功" if manager.unload_module("math") else "失败")
    
    # 卸载模块
    manager.unload_module("datetime")
    
    # 关闭管理器
    manager.shutdown()
