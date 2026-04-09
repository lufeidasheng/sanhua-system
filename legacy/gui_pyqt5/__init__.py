# gui/__init__.py

# 这里统一导入 gui 包里的主要控件组件和主窗口类
from .main_gui import AICoreGUI
from .widgets.chat_box import ChatBox
from .widgets.input_bar import InputBar
from .widgets.status_panel import StatusPanel
from .widgets.menu_bar import MenuBar
from .widgets.background_manager import BackgroundManager

# 也可以根据需要暴露一些工具函数、常量等
# from .utils.some_util import some_function
