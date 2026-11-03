"""Видимый указатель агента и отменяемый ввод Windows."""
import ctypes
import os
import threading

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from capri.core import cancellation


class AgentCursor(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(80, 52)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def mark(self, x, y):
        self.move(round(x)-12, round(y)-12)
        self.show()
        self.timer.start(1200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ff224c"), 2))
        painter.drawEllipse(3, 3, 18, 18)
        painter.drawLine(12, 0, 12, 25)
        painter.drawLine(0, 12, 25, 12)
        painter.drawText(2, 43, "CAPRI")


class PointerTools(QObject):
    moved = Signal(float, float)
    move_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.overlay = AgentCursor()
        self.moved.connect(self.overlay.mark)
        self.move_requested.connect(self._move)

    def _move(self, state):
        from PySide6.QtGui import QCursor
        try:
            QCursor.setPos(QPoint(round(state["x"]),round(state["y"])))
            self.moved.emit(state["x"],state["y"])
        finally:
            state["ready"].set()

    def available(self):
        cancellation.checkpoint()
        if os.name != "nt" or QGuiApplication.platformName() == "offscreen":
            raise ValueError("Ввод агента доступен в обычном сеансе Windows.")

    def click(self, x, y, action="click"):
        self.available()
        from PySide6.QtGui import QCursor
        state = {"x":x,"y":y,"ready":threading.Event()}
        self.move_requested.emit(state)
        if not cancellation.wait_event(state["ready"],2):
            raise ValueError("Указатель не перемещён")
        cancellation.wait(.1)
        point = QCursor.pos()
        if abs(point.x()-x)>3 or abs(point.y()-y)>3:
            raise ValueError("Курсор переместился: клик отменён")
        user = ctypes.windll.user32
        down, up = (8, 16) if action == "right_click" else (2, 4)
        for _ in range(2 if action == "double_click" else 1):
            cancellation.checkpoint()
            user.mouse_event(down, 0, 0, 0, 0)
            user.mouse_event(up, 0, 0, 0, 0)
            cancellation.wait(.08)

    def type_text(self, text):
        self.available()
        from capri.automation.window_input import type_text
        type_text(text, delay=.002)

    def key(self, sequence):
        self.available()
        aliases = {"CTRL":17,"ALT":18,"SHIFT":16,"WIN":91,"ENTER":13,"TAB":9,"ESC":27,
                   "BACKSPACE":8,"DELETE":46,"SPACE":32,"HOME":36,"END":35,"LEFT":37,"UP":38,"RIGHT":39,"DOWN":40}
        keys = []
        for part in sequence.upper().split("+"):
            part = part.strip()
            code = aliases.get(part, ord(part) if len(part) == 1 and part.isascii() else None)
            if code is None:
                raise ValueError("Неизвестная клавиша: " + part)
            keys.append(code)
        if not keys or len(keys) > 5:
            raise ValueError("Неверное сочетание")
        pressed = []
        try:
            for key in keys:
                cancellation.checkpoint()
                ctypes.windll.user32.keybd_event(key, 0, 0, 0)
                pressed.append(key)
        finally:
            for key in reversed(pressed):
                ctypes.windll.user32.keybd_event(key, 0, 2, 0)

    def scroll(self, notches):
        self.available()
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, ctypes.c_uint32(-120*int(notches)).value, 0)
