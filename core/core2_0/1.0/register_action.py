import logging
from functools import wraps
from typing import Callable, Dict, Any, Union, Optional, List, Type

# 全局动作注册表
ACTION_REGISTRY: Dict[str, Callable] = {}

# 配置日志
logger = logging.getLogger("ActionDispatcher")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# 注册策略枚举
class RegistrationPolicy:
    OVERWRITE = "overwrite"  # 覆盖现有动作
    IGNORE = "ignore"        # 忽略新注册
    ERROR = "error"          # 抛出异常
    WARNING = "warning"      # 发出警告并覆盖

# 默认注册策略
DEFAULT_POLICY = RegistrationPolicy.OVERWRITE

def register_action(
    name: Union[str, List[str], None] = None,
    *,
    policy: str = DEFAULT_POLICY,
    module: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    version: Optional[str] = None,
    deprecated: bool = False
):
    """
    注册动作到全局注册表的装饰器
    
    参数:
        name: 动作名称（可以是字符串或字符串列表）
        policy: 名称冲突处理策略 ('overwrite', 'ignore', 'error', 'warning')
        module: 所属模块名称
        description: 动作描述
        category: 动作分类
        version: 动作版本
        deprecated: 是否已弃用
        
    使用示例:
        1. 基本用法:
            @register_action("my_action")
            def my_function(): ...
            
        2. 多个名称:
            @register_action(["action1", "action2"])
            def my_function(): ...
            
        3. 带元数据:
            @register_action("complex_action", 
                             description="执行复杂操作",
                             category="utils",
                             version="1.2")
            def complex_operation(): ...
            
        4. 自动命名:
            @register_action
            def another_action(): ...
    """
    # 处理无参数直接装饰的情况 (@register_action)
    if callable(name):
        func = name
        action_names = [func.__name__]
        return _register(action_names, func, policy, module, description, category, version, deprecated)
    
    # 处理带参数装饰的情况
    def decorator(func):
        # 确定动作名称
        if name is None:
            action_names = [func.__name__]
        elif isinstance(name, str):
            action_names = [name]
        elif isinstance(name, list):
            action_names = name
        else:
            raise TypeError("name 必须是字符串、字符串列表或None")
        
        return _register(action_names, func, policy, module, description, category, version, deprecated)
    
    return decorator

def _register(
    names: List[str],
    func: Callable,
    policy: str,
    module: Optional[str],
    description: Optional[str],
    category: Optional[str],
    version: Optional[str],
    deprecated: bool
) -> Callable:
    """实际执行注册的内部函数"""
    # 获取调用模块信息（如果未提供）
    if module is None:
        module = func.__module__
    
    # 为函数添加元数据
    func._action_metadata = {
        "names": names,
        "module": module,
        "description": description or func.__doc__,
        "category": category,
        "version": version,
        "deprecated": deprecated,
        "original_name": func.__name__,
        "source_file": getattr(func, "__code__", {}).get("co_filename", "unknown")
    }
    
    # 处理每个动作名称
    for action_name in names:
        # 检查名称冲突
        if action_name in ACTION_REGISTRY:
            existing_func = ACTION_REGISTRY[action_name]
            existing_module = getattr(existing_func, "_action_metadata", {}).get("module", "unknown")
            
            conflict_msg = (
                f"动作名称冲突: '{action_name}' "
                f"(由 {module} 注册, 已由 {existing_module} 注册)"
            )
            
            if policy == RegistrationPolicy.ERROR:
                raise ValueError(conflict_msg)
            elif policy == RegistrationPolicy.IGNORE:
                logger.debug(f"{conflict_msg} - 根据策略忽略")
                continue
            elif policy == RegistrationPolicy.WARNING:
                logger.warning(f"{conflict_msg} - 根据策略覆盖")
        
        # 注册动作
        ACTION_REGISTRY[action_name] = func
        logger.info(f"注册动作: {action_name} (来自模块: {module})")
    
    # 保留原始函数元数据
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    
    # 将元数据附加到包装函数
    wrapper._action_metadata = func._action_metadata
    return wrapper

def get_action(name: str) -> Optional[Callable]:
    """根据名称获取注册的动作"""
    return ACTION_REGISTRY.get(name)

def list_actions() -> Dict[str, Dict[str, Any]]:
    """列出所有注册的动作及其元数据"""
    actions_info = {}
    for name, func in ACTION_REGISTRY.items():
        # 获取元数据，如果不存在则创建基本元数据
        metadata = getattr(func, "_action_metadata", {})
        if not metadata:
            metadata = {
                "names": [name],
                "module": getattr(func, "__module__", "unknown"),
                "description": getattr(func, "__doc__", ""),
                "category": "uncategorized",
                "version": "unknown",
                "deprecated": False,
                "original_name": func.__name__,
                "source_file": getattr(getattr(func, "__code__", {}), "co_filename", "unknown")
            }
        
        actions_info[name] = metadata
    return actions_info

def unregister_action(name: str) -> bool:
    """取消注册指定动作"""
    if name in ACTION_REGISTRY:
        del ACTION_REGISTRY[name]
        logger.info(f"已取消注册动作: {name}")
        return True
    return False

def clear_actions():
    """清除所有注册的动作"""
    ACTION_REGISTRY.clear()
    logger.info("已清除所有注册的动作")

# 示例用法
if __name__ == "__main__":
    # 基本用法
    @register_action("simple_action")
    def simple_function():
        """简单的动作函数"""
        return "Simple action executed"
    
    # 多个名称
    @register_action(["action1", "action2"])
    def multi_name_action():
        return "Multi-name action"
    
    # 自动命名
    @register_action
    def auto_named_action():
        """自动命名动作"""
        return "Auto-named action"
    
    # 带元数据
    @register_action(
        "complex_action", 
        description="执行复杂操作",
        category="utils",
        version="1.2",
        deprecated=False
    )
    def complex_operation(a: int, b: int) -> int:
        return a + b
    
    # 测试冲突处理
    try:
        @register_action("simple_action", policy=RegistrationPolicy.ERROR)
        def conflict_action():
            return "This should cause an error"
    except ValueError as e:
        print(f"捕获到预期冲突: {e}")
    
    # 列出所有动作
    print("\n注册的动作:")
    for name, metadata in list_actions().items():
        print(f"- {name}: {metadata['description']} (模块: {metadata['module']})")
    
    # 执行动作
    print("\n执行动作:")
    print("simple_action:", get_action("simple_action")())
    print("action1:", get_action("action1")())
    print("auto_named_action:", get_action("auto_named_action")())
    print("complex_action(2, 3):", get_action("complex_action")(2, 3))
