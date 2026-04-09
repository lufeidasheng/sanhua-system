# utils/__init__.py

# 假设你有多个工具模块，比如 typing_effect.py, system_monitor.py 等
from .typing_effect import TypingEffect
from .system_monitor import SystemMonitor

# 你也可以暴露单个函数或多个类
# from .file_utils import read_file, write_file

# 如果你有初始化逻辑，也可以写在这里，但通常 utils 纯工具模块不需要
