# modules/gui_entry/gui_main.py
import os
from PyQt6 import QtWidgets, QtGui, QtCore

class MainWindow(QtWidgets.QMainWindow):
    """主窗口 - 三花聚顶系统的GUI界面"""
    
    def __init__(self, event_publisher, config):
        super().__init__()
        self.event_publisher = event_publisher
        self.config = config
        self.setup_ui()
        self.setWindowTitle("三花聚顶 · 智控中心")
        self.setGeometry(100, 100, 900, 600)
        
        # 初始化状态
        self.system_status = {
            "status": "stopped",
            "modules": {},
            "health": "unknown"
        }

    def setup_ui(self):
        """设置用户界面"""
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        
        # 主布局
        main_layout = QtWidgets.QVBoxLayout(main_widget)
        
        # 顶部状态栏
        status_bar = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("系统状态: 正在启动...")
        self.health_label = QtWidgets.QLabel("健康状态: 未知")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()
        status_bar.addWidget(self.health_label)
        main_layout.addLayout(status_bar)
        
        # 控制按钮
        control_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("启动系统")
        self.start_btn.clicked.connect(self.start_system)
        self.stop_btn = QtWidgets.QPushButton("停止系统")
        self.stop_btn.clicked.connect(self.stop_system)
        self.stop_btn.setEnabled(False)
        self.restart_btn = QtWidgets.QPushButton("重启系统")
        self.restart_btn.clicked.connect(self.restart_system)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.restart_btn)
        control_layout.addStretch()
        
        main_layout.addLayout(control_layout)
        
        # 模块状态表格
        self.module_table = QtWidgets.QTableWidget()
        self.module_table.setColumnCount(4)
        self.module_table.setHorizontalHeaderLabels(["模块", "状态", "健康", "操作"])
        self.module_table.setColumnWidth(0, 200)
        self.module_table.setColumnWidth(1, 100)
        self.module_table.setColumnWidth(2, 100)
        self.module_table.setColumnWidth(3, 150)
        
        main_layout.addWidget(self.module_table)
        
        # 系统响应区域
        response_group = QtWidgets.QGroupBox("系统响应")
        response_layout = QtWidgets.QVBoxLayout()
        self.response_text = QtWidgets.QTextEdit()
        self.response_text.setReadOnly(True)
        response_layout.addWidget(self.response_text)
        response_group.setLayout(response_layout)
        
        main_layout.addWidget(response_group)
        
        # 粒子效果占位
        self.particle_label = QtWidgets.QLabel()
        self.particle_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.particle_label.setText("粒子效果区域")
        self.particle_label.setStyleSheet("background-color: #1a1a2e; color: #e6e6e6; border-radius: 10px;")
        main_layout.addWidget(self.particle_label)
        
        # 底部状态栏
        self.footer = QtWidgets.QStatusBar()
        self.setStatusBar(self.footer)
        self.footer.showMessage("三花聚顶系统已就绪")

    def start_system(self):
        """启动系统"""
        self.event_publisher("SYSTEM_COMMAND", {"command": "start"}, requester_role="gui")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_system(self):
        """停止系统"""
        self.event_publisher("SYSTEM_COMMAND", {"command": "stop"}, requester_role="gui")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def restart_system(self):
        """重启系统"""
        self.event_publisher("SYSTEM_COMMAND", {"command": "restart"}, requester_role="gui")

    def update_system_status(self, status_data: dict):
        """更新系统状态"""
        self.system_status = status_data
        self.status_label.setText(f"系统状态: {status_data.get('status', 'unknown')}")
        self.health_label.setText(f"健康状态: {status_data.get('health', 'unknown')}")
        
        # 更新状态栏颜色
        status = status_data.get('status', 'stopped')
        if status == "running":
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        elif status == "starting":
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        
        # 健康状态
        health = status_data.get('health', 'unknown')
        if health == "healthy":
            self.health_label.setStyleSheet("color: green; font-weight: bold;")
        elif health == "warning":
            self.health_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.health_label.setStyleSheet("color: red; font-weight: bold;")

    def update_module_status(self, module_data: dict):
        """更新模块状态"""
        module_name = module_data["name"]
        status = module_data["status"]
        health = module_data["health"]
        
        # 查找或创建模块行
        row = -1
        for i in range(self.module_table.rowCount()):
            if self.module_table.item(i, 0).text() == module_name:
                row = i
                break
        
        if row == -1:
            row = self.module_table.rowCount()
            self.module_table.insertRow(row)
            self.module_table.setItem(row, 0, QtWidgets.QTableWidgetItem(module_name))
            self.module_table.setItem(row, 1, QtWidgets.QTableWidgetItem(status))
            self.module_table.setItem(row, 2, QtWidgets.QTableWidgetItem(health))
            
            # 添加操作按钮
            btn_frame = QtWidgets.QWidget()
            btn_layout = QtWidgets.QHBoxLayout()
            restart_btn = QtWidgets.QPushButton("重启")
            restart_btn.clicked.connect(lambda _, m=module_name: self.restart_module(m))
            unload_btn = QtWidgets.QPushButton("卸载")
            unload_btn.clicked.connect(lambda _, m=module_name: self.unload_module(m))
            
            btn_layout.addWidget(restart_btn)
            btn_layout.addWidget(unload_btn)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_frame.setLayout(btn_layout)
            self.module_table.setCellWidget(row, 3, btn_frame)
        else:
            self.module_table.item(row, 1).setText(status)
            self.module_table.item(row, 2).setText(health)
        
        # 设置状态颜色
        if status == "running":
            self.module_table.item(row, 1).setForeground(QtGui.QColor(0, 128, 0))
        elif status == "stopped":
            self.module_table.item(row, 1).setForeground(QtGui.QColor(255, 0, 0))
        else:
            self.module_table.item(row, 1).setForeground(QtGui.QColor(0, 0, 255))
            
        # 设置健康颜色
        if health == "healthy":
            self.module_table.item(row, 2).setForeground(QtGui.QColor(0, 128, 0))
        elif health == "warning":
            self.module_table.item(row, 2).setForeground(QtGui.QColor(255, 165, 0))
        else:
            self.module_table.item(row, 2).setForeground(QtGui.QColor(255, 0, 0))

    def restart_module(self, module_name):
        """重启指定模块"""
        self.event_publisher("MODULE_COMMAND", {
            "command": "restart",
            "module": module_name
        }, requester_role="gui")

    def unload_module(self, module_name):
        """卸载指定模块"""
        self.event_publisher("MODULE_COMMAND", {
            "command": "unload",
            "module": module_name
        }, requester_role="gui")

    def show_system_response(self, response_data: dict):
        """显示系统响应"""
        text = response_data.get("text", "")
        self.response_text.append(f"[系统] {text}")
        
        # 滚动到底部
        self.response_text.verticalScrollBar().setValue(
            self.response_text.verticalScrollBar().maximum()
        )
        
        # 粒子效果模拟
        self.particle_label.setText(f"粒子效果: {text[:20]}...")

def register_actions(dispatcher):
    """
    注册模块动作接口。
    通过 dispatcher.register_action 注册关键词与回调函数绑定，例如：

        dispatcher.register_action("关键词", your_function, module_name="modules.gui_entry.gui_main")

    注意替换 "关键词" 与 your_function。
    """
    pass
