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
            if not state.get("cancelled"):
                QCursor.setPos(QPoint(round(state["x"]),round(state["y"])))
                self.moved.emit(state["x"],state["y"])
        finally:
            state["ready"].set()

    def available(self):
        cancellation.checkpoint()
        if os.name != "nt" or QGuiApplication.platformName() == "offscreen":
            raise ValueError("Ввод агента доступен в обычном сеансе Windows.")

    def move(self, x, y):
        self.available()
        from PySide6.QtGui import QCursor
        state = {"x":x,"y":y,"ready":threading.Event()}
        self.move_requested.emit(state)
        try:
            if not cancellation.wait_event(state["ready"],2):
                raise ValueError("Указатель не перемещён")
        finally:
            state["cancelled"] = True
        cancellation.wait(.1)
        point = QCursor.pos()
        if abs(point.x()-x)>3 or abs(point.y()-y)>3:
            raise ValueError("Курсор переместился: клик отменён")

    def click(self, x, y, action="click"):
        self.move(x, y)
        user = ctypes.windll.user32
        down, up = {"right_click": (8,16), "middle_click": (32,64)}.get(action, (2,4))
        for _ in range(2 if action == "double_click" else 1):
            cancellation.checkpoint()
            user.mouse_event(down, 0, 0, 0, 0)
            user.mouse_event(up, 0, 0, 0, 0)
            cancellation.wait(.08)

    def type_text(self, text):
        self.available()
        from capri.automation.window_input import type_text
        type_text(text, delay=.002)

    @staticmethod
    def key_codes(sequence):
        aliases = {"CTRL":17,"ALT":18,"SHIFT":16,"WIN":91,"ENTER":13,"TAB":9,"ESC":27,
                   "BACKSPACE":8,"DELETE":46,"SPACE":32,"HOME":36,"END":35,"LEFT":37,"UP":38,"RIGHT":39,"DOWN":40,
                   "CONTROL":17,"ESCAPE":27,"RETURN":13,"SUPER":91,"META":91,"CMD":91,"COMMAND":91,
                   "ARROWLEFT":37,"ARROWUP":38,"ARROWRIGHT":39,"ARROWDOWN":40,
                   "PAGEUP":33,"PAGEDOWN":34,"PGUP":33,"PGDN":34,"INSERT":45,"CAPSLOCK":20,
                   "PLUS":187,"MINUS":189}
        aliases.update({f"F{i}":111+i for i in range(1,25)})
        keys = []
        for part in sequence.upper().split("+"):
            part = part.strip()
            code = aliases.get(part, ord(part) if len(part) == 1 and part.isascii() else None)
            if code is None:
                raise ValueError("Неизвестная клавиша: " + part)
            keys.append(code)
        if not keys or len(keys) > 5:
            raise ValueError("Неверное сочетание")
        return keys

    def key(self, sequence):
        self.available()
        keys = self.key_codes(sequence)
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

    def scroll_pixels(self, dx, dy):
        self.available()
        for amount, flag in ((dy,0x0800),(dx,0x1000)):
            if amount:
                ticks = max(1, round(abs(amount)/100)) * (1 if amount > 0 else -1)
                ctypes.windll.user32.mouse_event(flag,0,0,ctypes.c_uint32(ticks*120*(-1 if flag==0x0800 else 1)).value,0)

    def drag(self, points):
        self.available()
        self.move(*points[0])
        user = ctypes.windll.user32
        cancellation.checkpoint()
        user.mouse_event(2,0,0,0,0)
        try:
            for point in points[1:]:
                cancellation.checkpoint()
                self.move(*point)
        finally:
            user.mouse_event(4,0,0,0,0)
