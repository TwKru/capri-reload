"""Векторная сцена подключения: киберголова и полёт в красный глаз.

Рисование зависит только от времени. Без видео, внешних ассетов, случайного
шума и блокировки Qt: кадры одинаковы в приложении, превью и тестах.
"""
import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)

from capri.ui.chip_art import RED, draw_chip, ease
from capri.ui.neural_head import EYE_CENTER, IRIS_RADIUS
from capri.ui.neural_head import draw_neural_head as _head


def _color(hex_value, alpha=255):
    color = QColor(hex_value)
    color.setAlpha(round(max(0,min(255,alpha))))
    return color


def _polygon(points):
    return QPolygonF([QPointF(x,y) for x,y in points])


@lru_cache(maxsize=1)
def _halo_image():
    """Маленькая текстура свечения вместо расчёта градиента всего экрана каждый кадр."""
    image=QImage(192,192,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    gradient=QRadialGradient(QPointF(96,96),96)
    gradient.setColorAt(0,_color("#461125",85))
    gradient.setColorAt(1,_color("#06070c",0))
    painter=QPainter(image)
    painter.fillRect(image.rect(),gradient)
    painter.end()
    return image


def _brackets(p, seconds, activation):
    p.save()
    p.setOpacity(ease(seconds/.35)*(1-ease((seconds-1.45)/.35)))
    p.setPen(QPen(_color("#ff224c",145),1))
    for sx in (-1,1):
        for sy in (-1,1):
            x,y=sx*141,sy*172
            p.drawPolyline(_polygon([(x-sx*22,y),(x,y),(x,y-sy*19)]))
    p.setPen(QPen(_color("#656978",120),.7))
    p.drawLine(-152,151,152,151)
    for x in range(-140,141,14):
        p.drawLine(x,151,x,147 if x%28 else 143)
    font=QFont("Consolas"); font.setPixelSize(10)
    p.setFont(font)
    p.setPen(_color("#a4a6af"))
    p.drawText(QRectF(-140,157,280,18),Qt.AlignmentFlag.AlignCenter,
               "CAPRI / CONNECTED" if activation>.7 else "CAPRI / CONNECTING")
    p.restore()


def _reveal(p, viewport, seconds):
    w,h=viewport.width(),viewport.height()
    margin=w*.12+40
    rows=10
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for index in range(rows):
        progress=ease((seconds-2.12-index*.04)/1.08)
        if progress>=1:
            continue
        direction=1 if index%2 else -1
        shift=(w+margin*2)*progress*direction
        y=index*h/rows
        skew=direction*(h/rows*.65)
        p.setBrush(RED)
        p.drawPolygon(_polygon([(-margin+shift,y),(w+margin+shift,y),
            (w+margin+shift+skew,y+h/rows+1),(-margin+shift+skew,y+h/rows+1)]))
        if .02<progress<.98:
            x=shift-margin if direction>0 else w+margin+shift
            p.setPen(QPen(_color("#ffbccb",90*(1-progress)),1.5))
            p.drawLine(QPointF(x,y),QPointF(x+skew,y+h/rows))
            p.setPen(Qt.PenStyle.NoPen)
    p.restore()


def eye_flight(viewport, center, camera_base, seconds):
    """Приближение сохраняет глаз на экране и заканчивается внутри красного диска."""
    progress=ease((seconds-1.08)/.88)
    reach=max(math.hypot(center.x()-x,center.y()-y) for x,y in (
        (viewport.left(),viewport.top()),(viewport.right(),viewport.top()),
        (viewport.left(),viewport.bottom()),(viewport.right(),viewport.bottom())))
    target=max(1.,reach/(camera_base*IRIS_RADIUS)*1.08)
    zoom=1+(target-1)*progress**3
    aim=center+EYE_CENTER*camera_base*(1-ease(progress/.55))
    return progress,zoom,aim


def paint_startup_scene(p, viewport, center, seconds):
    """Сцена длиной 3,6 с: приближение, контакт, заливка и раскрытие рабочего стола."""
    t=max(0.,seconds)
    if t>=3.5:
        return
    if t>=1.96:
        if t<=2.12:
            p.fillRect(viewport,RED)
        else:
            _reveal(p,viewport,t)
        return
    background=ease(t/.22)
    p.fillRect(viewport,_color("#06070c",244*background))
    radius=min(viewport.width(),viewport.height())*.58
    p.save()
    p.setOpacity(background)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(center.x()-radius,center.y()-radius,radius*2,radius*2),_halo_image())
    p.restore()
    scale=max(.45,min(viewport.width()/760,viewport.height()/620,1.75))
    arrival=ease(t/.55)
    activation=ease((t-.94)/.19)
    flight=eye_flight(viewport,center,camera_base=scale*(.92+.08*arrival+.035*activation),seconds=t)
    camera_scale=scale*(.92+.08*arrival+.035*activation)
    p.save()
    if flight[0]>0:
        progress,zoom,aim=flight
        p.translate(aim)
        p.scale(camera_scale*zoom,camera_scale*zoom)
        p.translate(-EYE_CENTER)
    else:
        progress=0.
        p.translate(center+QPointF(0,14*(1-arrival)*scale))
        p.scale(camera_scale,camera_scale)
        p.rotate(-3*(1-arrival))
    p.setOpacity(ease(t/.2))
    _brackets(p,t,activation)
    insertion=ease((t-.24)/.79)
    distance=(1-insertion)*305
    p.save()
    p.translate(74+distance,-71-23*(1-insertion))
    p.rotate(-12*(1-insertion))
    draw_chip(p,QRectF(0,-23,94,51))
    p.restore()
    _head(p,activation,t,eye_focus=progress)
    # Короткий импульс контакта, без мерцания всего экрана.
    impact=max(0,1-abs(t-1.04)/.12)
    if impact>0:
        p.setPen(QPen(_color("#ffe1e7",200*impact),1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius=10+22*(1-impact)
        p.drawEllipse(QPointF(99,-71),radius,radius)
    p.restore()
    # Непрерывное нарастание до гарантированного покрытия виртуального экрана.
    cover=ease((t-1.72)/.24)
    if cover>0:
        p.fillRect(viewport,_color("#ff224c",255*cover))
