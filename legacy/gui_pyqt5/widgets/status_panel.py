from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt

class StatusPanel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignRight)
        self.setStyleSheet("color: #666; font-size: 10px;")
        self.setText("就绪")

    def setText(self, text):
        super().setText(text or "就绪")
