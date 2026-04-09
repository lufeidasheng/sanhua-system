# core/aicore/__init__.py
# 只做“最小导出”，避免导入时把整个系统依赖拉爆

from .config import AICoreConfig

# 延迟导入，避免循环依赖/缺依赖直接炸
def get_aicore_class():
    from .aicore import AICore
    return AICore

def get_extensible_class():
    from .extensible_aicore import ExtensibleAICore
    return ExtensibleAICore

# 兼容你测试脚本的写法：from core.aicore import ExtensibleAICore
from .extensible_aicore import ExtensibleAICore
