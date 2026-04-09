from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor

class ChatBox(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setStyleSheet("""
            QTextEdit {
                background: rgba(255, 255, 255, 0.7);
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                color: #222;
            }
        """)

    def append_chat(self, role, text):
        role_format = QTextCharFormat()
        if role == "用户":
            role_format.setForeground(QColor("#1a5fb4"))  # 蓝色
            role_format.setFontWeight(75)  # 加粗
        elif role == "聚核助手":
            role_format.setForeground(QColor("#c64600"))  # 橙色
            role_format.setFontWeight(75)
        else:
            role_format.setForeground(QColor("#555"))  # 灰色

        text_format = QTextCharFormat()
        text_format.setForeground(QColor("#333"))  # 深灰色

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{role}：", role_format)
        cursor.insertText(text, text_format)
        cursor.insertText("\n")
        self.ensureCursorVisible()
