"""Полноэкранные заставки подключения и извлечения чипа Капри."""
import math
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

RED = QColor("#ff224c")
DARK = QColor("#08080c")


def ease(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def draw_chip(painter, rect):
    """Один рисунок для анимации и значка трея: красный аниме-чип с контактами."""
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 100, rect.height() / 54)
    painter.setPen(QPen(QColor("#09090b"), 3))
    painter.setBrush(QColor("#aab0b7"))
    painter.drawRoundedRect(QRectF(1, 12, 30, 30), 2, 2)
    painter.setPen(QPen(QColor("#34343e"), 2))
    for y in (19, 27, 35):
        painter.drawLine(6, y, 23, y)
    painter.setPen(QPen(QColor("#09090b"), 3))
    painter.setBrush(RED)
    painter.drawPolygon(QPolygonF([QPointF(28, 2), QPointF(88, 2), QPointF(98, 12),
        QPointF(98, 43), QPointF(87, 52), QPointF(28, 52)]))
    painter.setBrush(DARK)
    painter.drawPolygon(QPolygonF([QPointF(38, 11), QPointF(78, 11), QPointF(87, 20),
        QPointF(87, 39), QPointF(38, 39)]))
    painter.setPen(QPen(QColor("#ffb8c7"), 2))
    painter.drawLine(43, 18, 69, 18)
    font = QFont("Consolas")
    font.setPixelSize(10)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(42, 22, 40, 15), Qt.AlignmentFlag.AlignLeft, "CAPRI")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffe1a1"))
    for x in (39, 49, 59, 69):
        painter.drawRect(x, 43, 6, 7)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRect(77, 27, 5, 5)
    painter.restore()


def chip_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(size / 2, size / 2)
        painter.rotate(-35)
        draw_chip(painter, QRectF(-size * .44, -size * .24, size * .88, size * .48))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def draw_head(painter):
    """Собственная чёрно-белая векторная киберголова, координаты вокруг её центра."""
    painter.save()
    skull = QPainterPath()
    skull.moveTo(-82, -92)
    skull.cubicTo(-90, -155, 73, -159, 85, -95)
    skull.lineTo(91, -24)
    skull.lineTo(67, -4)
    skull.lineTo(57, 69)
    skull.lineTo(27, 95)
    skull.lineTo(-26, 95)
    skull.lineTo(-58, 69)
    skull.lineTo(-67, -4)
    skull.lineTo(-88, -28)
    skull.closeSubpath()
    painter.setPen(QPen(QColor("#f2f2f2"), 3))
    painter.setBrush(QColor("#bfc1c7"))
    painter.drawPath(skull)
    painter.setBrush(QColor("#efeff1"))
    painter.drawPolygon(QPolygonF([QPointF(-66, -96), QPointF(30, -126), QPointF(70, -90),
        QPointF(60, -48), QPointF(6, -34), QPointF(-63, -57)]))
    painter.setPen(QPen(QColor("#282830"), 3))
    for points in ([(-69, -76), (-32, -63), (-32, -28)], [(26, -121), (26, -83), (64, -67)],
                   [(-55, 31), (-31, 45), (-30, 67)], [(57, 28), (34, 45), (32, 67)]):
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.setBrush(QColor("#08080b"))
    for x in (-48, 16):
        painter.drawPolygon(QPolygonF([QPointF(x, -26), QPointF(x + 34, -19),
            QPointF(x + 28, 5), QPointF(x + 2, 0)]))
    painter.drawPolygon(QPolygonF([QPointF(0, 2), QPointF(-12, 28), QPointF(12, 28)]))
    painter.drawRoundedRect(QRectF(-29, 51, 58, 22), 3, 3)
    painter.setPen(QPen(QColor("#e9e9ee"), 2))
    for x in (-20, -10, 0, 10, 20):
        painter.drawLine(x, 53, x, 69)
    painter.setPen(QPen(QColor("#16161c"), 6))
    painter.drawLine(75, -77, 95, -77)
    painter.setPen(QPen(QColor("#f2f2f2"), 2))
    painter.drawEllipse(QRectF(-95, -48, 23, 44))
    painter.drawEllipse(QRectF(76, -48, 23, 44))
    painter.restore()


class ScreenTransition(QWidget):
    finished = Signal(str)
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
        self.head_center = QPointF()

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
            self.outgoing_pos = (QPointF(avatar.pos() - geometry.topLeft()) if avatar.isVisible()
                else self.head_center + QPointF(-170, -40))
        self.mode = mode
        self.elapsed.start()
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def _tick(self):
        if self.mode is None:
            return
        if self.elapsed.elapsed() >= self.DURATIONS[self.mode] * 1000:
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
        """Детерминированная отрисовка также используется для проверки кадров без ожидания."""
        t = max(0., seconds)
        w, h = self.width(), self.height()
        center = self.head_center if not self.head_center.isNull() else QPointF(w / 2, h / 2)
        scale = max(.65, min(w / 1000, h / 720, 1.8))
        if mode == "startup":
            background = ease(t / .3) * (1 - ease((t - 2.1) / .65))
        else:
            background = ease(t / .25) * (1 - ease((t - 1.9) / .7))
        painter.fillRect(self.rect(), QColor(4, 4, 8, round(235 * background)))
        painter.save()
        painter.translate(center)
        painter.scale(scale, scale)
        if mode == "shutdown":
            fall = ease((t - 1.05) / 1.1)
            painter.translate(0, (h / scale + 220) * fall * fall)
            painter.rotate(16 * fall)
        head_opacity = ease(t / .2) * (1 - ease((t - 1.7) / .3) if mode == "startup" else 1)
        painter.setOpacity(head_opacity)
        draw_head(painter)
        insertion = ease((t - .3) / .75)
        distance = (1 - insertion) * 280 if mode == "startup" else ease((t - .25) / .75) * 280
        painter.setOpacity(head_opacity * (1 if mode == "startup" else 1 - ease((t - 1.15) / .4)))
        draw_chip(painter, QRectF(86 + distance, -93, 76, 41))
        painter.restore()

        if mode == "startup" and t >= 1.05:
            growth = ease((t - 1.05) / .95)
            origin = center + QPointF(90 * scale, -76 * scale)
            reach = math.hypot(w, h) * 1.4
            painter.save()
            painter.translate(origin)
            painter.setOpacity(1 if t <= 2.05 else 0)
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(8):
                painter.save()
                painter.rotate(index * 45 + 12)
                painter.setBrush(RED if index % 2 else QColor("#b60e32"))
                painter.drawRect(QRectF(0, -max(2, reach * .26 * growth) / 2, reach * growth,
                                        max(2, reach * .26 * growth)))
                painter.restore()
            painter.restore()
            cover = ease((t - 1.7) / .3)
            if t <= 2.05:
                painter.fillRect(self.rect(), QColor(255, 34, 76, round(255 * cover)))
            else:
                for index in range(7):
                    shift = (w + h * .3) * ease((t - 2.05 - index * .055) / 1.05)
                    y = index * h / 7
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(RED if index % 3 else QColor("#c00e37"))
                    painter.drawPolygon(QPolygonF([QPointF(shift, y), QPointF(w + shift, y),
                        QPointF(w + shift + 80, y + h / 7 + 1), QPointF(shift + 80, y + h / 7 + 1)]))
        if mode == "shutdown" and self.outgoing is not None:
            fall = ease((t - 1.05) / 1.35)
            painter.save()
            painter.translate(self.outgoing_pos + QPointF(0, (h + 450) * fall * fall))
            painter.translate(170, 190)
            painter.rotate(28 * fall)
            painter.drawImage(QRectF(-170, -190, 340, 380), self.outgoing)
            painter.restore()
