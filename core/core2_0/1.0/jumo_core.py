import importlib.util
import os
import sys
import traceback
import logging
import asyncio
from threading import RLock
from copy import deepcopy
from typing import Dict, Optional, Set, Tuple, Any, List
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

@dataclass
class ModuleMetadata:
    """模块元数据标准化类"""
    id: str
    name: str
    version: str = "1.0.0"
    dependencies: List[str] = None
    init_func: str = "init"
    entry_func: str = "start"
    stop_func: str = "stop"
    events: List[str] = None
    config_schema: Dict = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.events is None:
            self.events = []

class JumoCore:
    def __init__(self, modules_path: str = "modules"):
        """
        增强版模块核心系统
        
        参数:
            modules_path: 模块目录路径
        """
        self.modules_path = Path(modules_path)
        self.modules: Dict[str, Any] = {}      # 模块对象
        self.metadata: Dict[str, ModuleMetadata] = {}  # 模块元数据
        self.status: Dict[str, str] = {}      # 模块状态
        self.config_map: Dict[str, Any] = {}   # 模块配置
        self.event_handlers = defaultdict(list) # 事件处理器映射
        self._lock = RLock()                   # 可重入锁
        self._loop = asyncio.get_event_loop()  # 事件循环
        
        # 初始化日志
        self.logger = logging.getLogger("JumoCore")
        self._setup_logging()
        
        # 确保模块目录存在
        self.modules_path.mkdir(exist_ok=True)

    def _setup_logging(self):
        """配置日志系统"""
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    async def load_module(self, module_name: str) -> Optional[Any]:
        """
        异步安全加载模块
        
        参数:
            module_name: 模块名称(不带.py后缀)
        返回:
            加载的模块对象或None
        """
        module_path = self.modules_path / f"{module_name}.py"
        
        try:
            # 使用aiofiles实现真正的异步文件读取
            async with aiofiles.open(module_path, "r", encoding="utf-8") as f:
                content = await f.read()
            
            # 创建模块规范
            spec = importlib.util.spec_from_file_location(
                module_name, 
                str(module_path),
                loader=None
            )
            
            if spec is None:
                self.logger.error(f"无法创建模块规范: {module_name}")
                return None
                
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            
            # 执行模块代码
            exec(content, module.__dict__)
            
            return module
        except Exception as e:
            self.logger.error(f"模块加载失败: {module_name}")
            self.logger.error(traceback.format_exc())
            return None

    async def discover_modules(self) -> bool:
        """
        异步发现并加载所有模块
        
        返回:
            是否全部模块加载成功
        """
        if not self.modules_path.exists():
            self.logger.error(f"模块目录不存在: {self.modules_path}")
            return False
            
        with self._lock:
            self.modules.clear()
            self.metadata.clear()
            self.status.clear()
            self.config_map.clear()
        
        sys.path.insert(0, str(self.modules_path))
        success = True
        
        # 使用异步任务并行加载模块
        tasks = []
        for filename in os.listdir(self.modules_path):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                tasks.append(self._load_single_module(module_name))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                success = False
                self.logger.error(f"模块加载异常: {str(result)}")
        
        return success

    async def _load_single_module(self, module_name: str) -> bool:
        """加载单个模块的内部方法"""
        mod = await self.load_module(module_name)
        if not mod:
            return False
            
        # 解析元数据
        raw_meta = getattr(mod, "__metadata__", None)
        try:
            if raw_meta:
                meta = ModuleMetadata(**raw_meta)
            else:
                meta = ModuleMetadata(
                    id=module_name,
                    name=module_name,
                    version="unknown"
                )
                self.logger.warning(f"发现未声明元信息模块: {module_name}")
            
            # 验证元数据
            if not meta.id:
                raise ValueError("模块ID不能为空")
            
            with self._lock:
                self.modules[meta.id] = mod
                self.metadata[meta.id] = meta
                self.status[meta.id] = "loaded"
                mod.__metadata__ = meta
            
            self.logger.info(f"模块加载成功: {meta.id} (v{meta.version})")
            return True
        except Exception as e:
            self.logger.error(f"模块元数据处理失败: {module_name}")
            self.logger.error(traceback.format_exc())
            return False

    async def initialize_module(self, module_id: str) -> bool:
        """异步初始化模块"""
        with self._lock:
            mod = self.modules.get(module_id)
            if not mod:
                self.logger.error(f"初始化失败: 模块不存在 - {module_id}")
                return False
                
            meta = self.metadata.get(module_id)
            current_status = self.status.get(module_id, "unknown")
            
            if current_status == "initialized":
                return True
        
        init_func_name = meta.init_func if meta else "init"
        
        try:
            init_func = getattr(mod, init_func_name, None)
            
            if init_func:
                self.logger.debug(f"正在初始化模块: {module_id} (函数: {init_func_name})")
                
                # 处理异步初始化函数
                if asyncio.iscoroutinefunction(init_func):
                    await init_func()
                elif callable(init_func):
                    init_func()
                
                with self._lock:
                    self.status[module_id] = "initialized"
                
                self.logger.info(f"模块初始化成功: {module_id}")
                return True
            else:
                with self._lock:
                    self.status[module_id] = "initialized"
                self.logger.debug(f"模块无需初始化: {module_id}")
                return True
        except Exception:
            with self._lock:
                self.status[module_id] = "error"
            self.logger.error(f"模块初始化失败: {module_id}")
            self.logger.error(traceback.format_exc())
            return False

    async def start_module(
        self, 
        module_id: str, 
        config: Optional[Dict] = None,
        visited: Optional[Set[str]] = None
    ) -> Tuple[bool, str]:
        """
        异步启动模块（带依赖解析）
        
        参数:
            module_id: 模块ID
            config: 模块配置
            visited: 用于检测循环依赖的集合
            
        返回:
            (是否成功, 消息)
        """
        if visited is None:
            visited = set()
            
        if module_id in visited:
            msg = f"检测到循环依赖: {module_id} -> {visited}"
            self.logger.error(msg)
            return False, msg
            
        visited.add(module_id)
        
        with self._lock:
            if module_id not in self.modules:
                msg = f"启动失败: 模块不存在 - {module_id}"
                self.logger.error(msg)
                return False, msg
                
            current_status = self.status.get(module_id, "unknown")
            if current_status == "running":
                return True, "already running"
            elif current_status == "error":
                self.logger.warning(f"尝试启动错误状态模块: {module_id}")
        
        # 存储配置
        if config is not None:
            self.config_map[module_id] = config
        
        # 处理依赖
        deps = self.metadata.get(module_id, ModuleMetadata(id=module_id)).dependencies
        self.logger.debug(f"模块 {module_id} 依赖: {deps}")
        
        for dep in deps:
            if dep not in self.modules:
                msg = f"模块 {module_id} 依赖缺失: {dep}"
                self.logger.error(msg)
                with self._lock:
                    self.status[module_id] = "error"
                return False, msg
                
            dep_status = self.status.get(dep, "unknown")
            if dep_status != "running":
                success, msg = await self.start_module(dep, self.config_map.get(dep), visited.copy())
                if not success:
                    with self._lock:
                        self.status[module_id] = "error"
                    return False, f"依赖启动失败: {msg}"
        
        # 确保初始化
        if current_status not in ["initialized", "running"]:
            if not await self.initialize_module(module_id):
                return False, f"初始化失败: {module_id}"
        
        # 启动模块
        mod = self.modules.get(module_id)
        meta = self.metadata.get(module_id)
        entry_func_name = meta.entry_func if meta else "start"
        
        try:
            entry_func = getattr(mod, entry_func_name, None)
            if entry_func is None:
                msg = f"模块缺少入口函数 '{entry_func_name}': {module_id}"
                self.logger.error(msg)
                with self._lock:
                    self.status[module_id] = "error"
                return False, msg
                
            self.logger.info(f"正在启动模块: {module_id} (函数: {entry_func_name})")
            
            # 处理异步/同步入口函数
            if asyncio.iscoroutinefunction(entry_func):
                await entry_func(deepcopy(config) if config else None)
            else:
                entry_func(deepcopy(config) if config else None)
                
            with self._lock:
                self.status[module_id] = "running"
                
            self.logger.info(f"模块启动成功: {module_id}")
            return True, "started"
        except Exception as e:
            with self._lock:
                self.status[module_id] = "error"
            self.logger.error(f"模块启动失败: {module_id}")
            self.logger.error(traceback.format_exc())
            return False, str(e)

    async def stop_module(self, module_id: str) -> bool:
        """异步停止模块"""
        with self._lock:
            mod = self.modules.get(module_id)
            if not mod:
                self.logger.error(f"停止失败: 模块不存在 - {module_id}")
                return False
                
            current_status = self.status.get(module_id, "unknown")
            if current_status != "running":
                self.logger.info(f"模块未运行: {module_id} (状态: {current_status})")
                return True
        
        try:
            meta = self.metadata.get(module_id)
            stop_func_name = meta.stop_func if meta else "stop"
            stop_func = getattr(mod, stop_func_name, None)
            
            if stop_func:
                self.logger.info(f"正在停止模块: {module_id}")
                
                if asyncio.iscoroutinefunction(stop_func):
                    await stop_func()
                else:
                    stop_func()
                
            with self._lock:
                self.status[module_id] = "stopped"
                
            self.logger.info(f"模块停止成功: {module_id}")
            return True
        except Exception:
            with self._lock:
                self.status[module_id] = "error"
            self.logger.error(f"模块停止失败: {module_id}")
            self.logger.error(traceback.format_exc())
            return False

    # 其他方法保持类似结构，添加异步支持...
    
    async def reload_module(self, module_id: str, config: Optional[Dict] = None) -> bool:
        """异步重新加载模块"""
        self.logger.info(f"重新加载模块: {module_id}")
        
        # 1. 停止模块
        if self.get_module_status(module_id) == "running":
            await self.stop_module(module_id)
        
        # 2. 卸载模块
        self.unload_module(module_id)
        
        # 3. 重新加载
        module_name = module_id  # 假设ID和文件名一致
        mod = await self.load_module(module_name)
        if not mod:
            return False
        
        # 4. 更新元数据
        raw_meta = getattr(mod, "__metadata__", None)
        try:
            meta = ModuleMetadata(**raw_meta) if raw_meta else ModuleMetadata(
                id=module_id,
                name=module_id,
                version="unknown"
            )
            
            with self._lock:
                self.modules[module_id] = mod
                self.metadata[module_id] = meta
                self.status[module_id] = "loaded"
                mod.__metadata__ = meta
            
            # 5. 重新启动
            return (await self.start_module(module_id, config))[0]
        except Exception:
            self.logger.error(f"模块重载失败: {module_id}")
            self.logger.error(traceback.format_exc())
            return False

    def register_event_handler(self, event_type: str, handler: callable):
        """注册事件处理器"""
        with self._lock:
            self.event_handlers[event_type].append(handler)
    
    async def emit_event(self, event_type: str, data: Optional[Dict] = None):
        """触发事件并通知所有处理器"""
        handlers = self.event_handlers.get(event_type, [])
        
        if not handlers:
            self.logger.debug(f"事件 {event_type} 无处理器")
            return
        
        self.logger.info(f"触发事件: {event_type} (处理器: {len(handlers)})")
        
        # 并行调用所有处理器
        tasks = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(handler(event_type, data or {}))
            else:
                # 同步函数在线程池中执行
                tasks.append(self._loop.run_in_executor(
                    None, handler, event_type, data or {}
                ))
        
        await asyncio.gather(*tasks, return_exceptions=True)

# 使用示例
async def main():
    core = JumoCore("modules")
    
    # 加载所有模块
    await core.discover_modules()
    
    # 启动特定模块
    await core.start_module("data_processor", {"config": "value"})
    
    # 触发事件
    await core.emit_event("data_ready", {"data": [...]})

if __name__ == "__main__":
    asyncio.run(main())
