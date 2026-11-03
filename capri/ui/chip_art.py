"""Полноэкранные заставки подключения и извлечения чипа Капри."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)

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
