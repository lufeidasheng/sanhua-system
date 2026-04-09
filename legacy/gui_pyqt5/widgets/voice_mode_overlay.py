# gui/widgets/voice_mode_overlay.py

import os
from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtGui import QPixmap, QMovie
from PyQt5.QtCore import Qt


class VoiceModeOverlay(QWidget):
    """
    管理语音模式下的浮动动画界面（如筋斗云）
    """

    def __init__(self, parent=None, gif_path="resources/cloud.gif"):
        super().__init__(parent)
        self.gif_path = gif_path
        self.init_ui()

    def init_ui(self):
        # 设置窗口样式：透明+无边框+置顶
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 云动画
        self.cloud_label = QLabel(self)
        self.cloud_label.setGeometry(200, 150, 320, 320)
        self.cloud_label.setScaledContents(True)

        if os.path.exists(self.gif_path):
            self.movie = QMovie(self.gif_path)
            self.cloud_label.setMovie(self.movie)
            self.movie.start()
        else:
            self.cloud_label.setText("⚠ 云动画未找到")

    def enter(self):
        self.show()

    def exit(self):
        self.hide()
