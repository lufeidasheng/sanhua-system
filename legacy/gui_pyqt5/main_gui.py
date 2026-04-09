import sys
import os
import threading

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QMessageBox,
)

from core.core2_0.sanhuatongyu.logger import TraceLogger

log = TraceLogger(__name__)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QMutex

from aicore import AICore
from aicore.memory.memory_manager import MemoryManager
from ju_wu.rule_trainer_widget import RuleTrainerWidget

from gui.widgets.chat_box import ChatBox
from gui.widgets.input_bar import InputBar
from gui.widgets.status_panel import StatusPanel
from gui.widgets.background_manager import BackgroundManager
from gui.widgets.menu_bar import MenuBar
from gui.widgets.voice_mode_overlay import VoiceModeOverlay
from gui.utils.voice_queue import VoiceQueue


class AICoreGUI(QWidget):
    append_text_signal = pyqtSignal(str, str)
    start_typing_signal = pyqtSignal(str, str)
    update_status_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.core = AICore()
        self.mem = MemoryManager()
        self.rule_trainer_window = None
        self.action_mutex = QMutex()
        self.active_future = None
        self.typing_timer = QTimer()

        # 读取背景图设置
        ui_settings = self.mem.memory.get("ui_settings", {})
        self.background_path = ui_settings.get("background_image_path", "")
        self.voice_enabled = True
        self.voice_queue = VoiceQueue()

        # 初始化 UI 子模块
        self.init_ui()

        # 语音模式覆盖层（筋斗云动画）
        self.voice_overlay = VoiceModeOverlay(self)

        # 信号绑定
        self.append_text_signal.connect(self.chat_box.append_chat)
        self.start_typing_signal.connect(self.start_typing_effect)
        self.update_status_signal.connect(self.status_panel.setText)
        self.typing_timer.timeout.connect(self._typing_effect)

        self.append_text_signal.emit("聚核助手", "你好，欢迎使用聚核助手！")

        # 系统资源监控
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.report_usage)
        self.monitor_timer.start(10000)

    def init_ui(self):
        self.setWindowTitle("三花聚顶·聚核助手")
        self.resize(900, 650)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)

        # 背景管理器
        self.background_manager = BackgroundManager(self)
        self.background_manager.update_background(self.background_path)

        # 菜单栏
        self.menu_bar = MenuBar(self)
        self.layout.setMenuBar(self.menu_bar)

        # 聊天区
        self.chat_box = ChatBox()
        self.layout.addWidget(self.chat_box)

        # 输入区
        self.input_bar = InputBar()
        self.layout.addWidget(self.input_bar)

        # 状态栏
        self.status_panel = StatusPanel()
        self.layout.addWidget(self.status_panel)

        # 绑定按钮和动作
        self.input_bar.send_button.clicked.connect(self.on_send)
        self.input_bar.voice_checkbox.stateChanged.connect(self.toggle_voice)

        # 绑定语音模式切换按钮（menu_bar.voice_mode_action）
        self.menu_bar.voice_mode_action.toggled.connect(self.toggle_voice_mode)

    def report_usage(self):
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info().rss / 1024 / 1024
            cpu = proc.cpu_percent(interval=0.1)
            status = f"内存: {mem:.2f} MB, CPU: {cpu:.2f}%"
            self.status_panel.setToolTip(status)
            print(f"[聚核助手资源占用] {status}")
        except:
            pass

    def toggle_voice(self):
        self.voice_enabled = self.input_bar.voice_checkbox.isChecked()
        if hasattr(self.core, "set_voice"):
            self.core.set_voice(self.voice_enabled)

    def on_send(self):
        query = self.input_bar.input_line.text().strip()
        if not query:
            return
        self.input_bar.send_button.setEnabled(False)
        self.status_panel.setText("处理中...")
        self.append_text_signal.emit("用户", query)
        self.input_bar.input_line.clear()

        threading.Thread(target=self.ask_core, args=(query,), daemon=True).start()

    def ask_core(self, query):
        try:
            self.update_status_signal.emit("思考中...")
            response = self.core.chat(query)

            if response.strip():
                self.start_typing_signal.emit("聚核助手", response)

            if self.voice_enabled and not getattr(self.core, "_looks_like_code", lambda x: False)(response):
                self.voice_queue.add(response)

            self.update_status_signal.emit("就绪")
        except Exception as e:
            self.append_text_signal.emit("系统错误", f"处理请求时出错: {e}")
            self.update_status_signal.emit(f"错误: {str(e)}")
        finally:
            self.input_bar.send_button.setEnabled(True)

    def start_typing_effect(self, role, text):
        self.typing_text = text
        self.typing_pos = 0
        self.typing_role = role
        self.typing_timer.start(30)

    def _typing_effect(self):
        if self.typing_pos >= len(self.typing_text):
            self.typing_timer.stop()
            return

        self.typing_pos += 1
        partial = self.typing_text[:self.typing_pos]
        self.chat_box.append_chat(self.typing_role, partial)

    # 语音模式切换，切换筋斗云动画覆盖层显示隐藏
    def toggle_voice_mode(self, enabled: bool):
        if enabled:
            self.enter_voice_mode()
        else:
            self.exit_voice_mode()

    def enter_voice_mode(self):
        # 隐藏聊天相关组件，显示透明动画覆盖层
        self.chat_box.hide()
        self.input_bar.hide()
        self.status_panel.hide()
        self.voice_overlay.enter()

    def exit_voice_mode(self):
        # 恢复聊天组件，隐藏覆盖层
        self.chat_box.show()
        self.input_bar.show()
        self.status_panel.show()
        self.voice_overlay.exit()

    # 记忆、状态、控制等功能示范
    def on_view_memory(self):
        self.ask_core("查看记忆")

    def on_import_memory(self):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "选择记忆 JSON 文件", "", "JSON Files (*.json)")
        if file_path:
            self.ask_core(f"导入记忆文件 {file_path}")

    def on_absorb_memory(self):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "选择对话记录文件", "", "JSON Files (*.json)")
        if file_path:
            self.ask_core(f"吸收外部记忆 {file_path}")

    def on_system_status(self):
        self.ask_core("系统状态")

    def on_control_panel(self):
        QMessageBox.information(self, "控制面板", "控制面板功能暂未实现，敬请期待！")

    def on_select_background(self):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            self.background_path = file_path
            self.background_manager.update_background(file_path)
            ui_settings = self.mem.memory.setdefault("ui_settings", {})
            ui_settings["background_image_path"] = file_path
            self.mem.save_memory()
            self.chat_box.append_chat("聚核助手", f"背景图片已更新：{file_path}")

    def open_rule_trainer(self):
        if self.rule_trainer_window is None:
            self.rule_trainer_window = RuleTrainerWidget()
            self.rule_trainer_window.destroyed.connect(
                lambda: setattr(self, 'rule_trainer_window', None)
            )
        self.rule_trainer_window.show()
        self.rule_trainer_window.raise_()
        self.rule_trainer_window.activateWindow()

    def closeEvent(self, event):
        self.voice_queue.clear()
        self.monitor_timer.stop()
        if hasattr(self.core, 'close'):
            self.core.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    gui = AICoreGUI()
    gui.show()

    sys.exit(app.exec_())
