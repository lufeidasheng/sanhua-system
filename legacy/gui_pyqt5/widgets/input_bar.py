from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QCheckBox

class InputBar(QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("请输入你的问题...")
        self.send_button = QPushButton("发送")
        self.voice_checkbox = QCheckBox("语音朗读")
        self.voice_checkbox.setChecked(True)

        self.layout.addWidget(self.input_line, 4)
        self.layout.addWidget(self.send_button, 1)
        self.layout.addWidget(self.voice_checkbox, 1)
