from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor

class TypingEffect:
    """打字机文字输出效果控制器"""

    def __init__(self, chat_box, update_status_callback=None):
        self.chat_box = chat_box
        self.timer = QTimer()
        self.timer.timeout.connect(self._typing_step)

        self.text = ""
        self.pos = 0
        self.role = ""
        self.cursor = None
        self.update_status = update_status_callback or (lambda msg: None)

    def start(self, role, text):
        if self.timer.isActive():
            self.timer.stop()
            self._finish()

        self.role = role
        self.text = text
        self.pos = 0

        # 创建新段落
        self.chat_box.moveCursor(QTextCursor.End)
        self.chat_box.insertPlainText(f"{self.role}： ")
        self.cursor = self.chat_box.textCursor()
        self.cursor.movePosition(QTextCursor.End)

        self.timer.start(30)
        self.update_status("输入中...")

    def _typing_step(self):
        if self.pos >= len(self.text):
            self.timer.stop()
            self.update_status("就绪")
            return

        self.pos += 1
        partial = self.text[:self.pos]

        cursor = self.chat_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.removeSelectedText()

        # 应用格式
        role_format = QTextCharFormat()
        role_format.setForeground(QColor("#c64600"))
        role_format.setFontWeight(75)

        text_format = QTextCharFormat()
        text_format.setForeground(QColor("#333"))

        cursor.insertText(f"{self.role}：", role_format)
        cursor.insertText(partial, text_format)

        self.chat_box.setTextCursor(cursor)
        self.chat_box.ensureCursorVisible()

    def _finish(self):
        if self.cursor and self.text and self.pos < len(self.text):
            remaining = self.text[self.pos:]
            if remaining:
                self.cursor.insertText(remaining)
            self.text = ""
            self.pos = 0
            self.update_status("就绪")

    def stop(self):
        if self.timer.isActive():
            self.timer.stop()
            self._finish()
