import os
from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

class BackgroundManager:
    def __init__(self, parent_widget):
        self.parent = parent_widget
        self.label = QLabel(parent_widget)
        self.label.setScaledContents(True)
        self.label.lower()
        self.pixmap = QPixmap()

    def update_background(self, path):
        if path and os.path.exists(path):
            self.pixmap = QPixmap(path)
            if not self.pixmap.isNull():
                scaled = self.pixmap.scaled(
                    self.parent.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                self.label.setPixmap(scaled)
                self.label.resize(self.parent.size())
        else:
            self.parent.setStyleSheet("background-color: #f0f0f0;")

    def resize(self):
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                self.parent.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.label.setPixmap(scaled)
            self.label.resize(self.parent.size())
