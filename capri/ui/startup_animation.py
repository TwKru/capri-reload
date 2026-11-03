"""Полноэкранные заставки: таймер, появление аватара и извлечение чипа."""
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from capri.ui.chip_art import chip_icon as chip_icon
from capri.ui.shutdown_scene import paint_shutdown_scene
from capri.ui.startup_scene import paint_startup_scene


class ScreenTransition(QWidget):
    finished = Signal(str)
    revealed = Signal()
    DURATIONS = {"startup": 3.6, "shutdown": 2.6}

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode = None
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.outgoing = None
        self.outgoing_pos = QPointF()
        self.outgoing_scale = 1.
        self.head_center = QPointF()
        self._revealed = False

    def play(self, mode, avatar=None):
        if mode not in self.DURATIONS:
            raise ValueError("Неизвестная заставка")
        self.timer.stop()
        screen = QGuiApplication.primaryScreen()
        geometry = screen.virtualGeometry()
        self.setGeometry(geometry)
        self.head_center = QPointF(screen.geometry().center() - geometry.topLeft())
        self.outgoing = None
        if mode == "shutdown" and avatar is not None:
            self.outgoing = QImage(avatar._figure())
            self.outgoing_scale = float(getattr(avatar,"scale_factor",1.))
            self.outgoing_pos = (QPointF(avatar.pos() - geometry.topLeft()) if avatar.isVisible()
                else self.head_center + QPointF(-170*self.outgoing_scale,30*self.outgoing_scale))
        self.mode = mode
        self._revealed = False
        self.elapsed.start()
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def _tick(self):
        if self.mode is None:
            return
        elapsed = self.elapsed.elapsed()
        if self.mode == "startup" and not self._revealed and elapsed >= 2750:
            self._revealed = True
            self.revealed.emit()
            self.raise_()  # аватар уже появляется, но ещё скрыт уходящими цветными панелями
            if self.mode != "startup":
                return
        if elapsed >= self.DURATIONS[self.mode] * 1000:
            mode, self.mode = self.mode, None
            self.timer.stop()
            self.hide()
            self.outgoing = None
            self.finished.emit(mode)
        else:
            self.update()

    def paintEvent(self, event):
        if self.mode is None:
            return
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw_frame(painter, self.mode, self.elapsed.elapsed() / 1000)
        painter.end()

    def draw_frame(self, painter, mode, seconds):
        """Детерминированные кадры также доступны без запуска таймера."""
        t = max(0., seconds)
        w, h = self.width(), self.height()
        center = self.head_center if not self.head_center.isNull() else QPointF(w / 2, h / 2)
        if mode == "startup":
            paint_startup_scene(painter, QRectF(self.rect()), center, t)
            return
        self._draw_shutdown(painter, center, t)

    def _draw_shutdown(self, painter, center, t):
        rect=QRectF(self.outgoing_pos.x(),self.outgoing_pos.y(),340*self.outgoing_scale,380*self.outgoing_scale)
        paint_shutdown_scene(painter,QRectF(self.rect()),center,t,self.outgoing,rect)
