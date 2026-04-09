from PyQt5.QtWidgets import QMenuBar, QMenu, QAction

class MenuBar(QMenuBar):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window

        # 功能菜单
        menu = QMenu("功能", self)
        self.addMenu(menu)

        # 创建各项功能动作
        act_view = QAction("查看记忆", self)
        act_import = QAction("导入记忆", self)
        act_absorb = QAction("吸收记忆", self)
        act_status = QAction("系统状态", self)
        act_control = QAction("控制面板", self)
        act_bg = QAction("更换背景图", self)
        act_train = QAction("意图训练器", self)

        # 添加动作到菜单
        menu.addActions([
            act_view, act_import, act_absorb,
            act_status, act_control, act_bg, act_train
        ])

        # 绑定动作触发事件到主窗口方法
        act_view.triggered.connect(main_window.on_view_memory)
        act_import.triggered.connect(main_window.on_import_memory)
        act_absorb.triggered.connect(main_window.on_absorb_memory)
        act_status.triggered.connect(main_window.on_system_status)
        act_control.triggered.connect(main_window.on_control_panel)
        act_bg.triggered.connect(main_window.on_select_background)
        act_train.triggered.connect(main_window.open_rule_trainer)

        # 模式菜单（语音模式切换）
        mode_menu = QMenu("模式", self)
        self.voice_mode_action = QAction("语音模式", self)
        self.voice_mode_action.setCheckable(True)
        self.voice_mode_action.toggled.connect(main_window.toggle_voice_mode)
        mode_menu.addAction(self.voice_mode_action)

        self.addMenu(mode_menu)
