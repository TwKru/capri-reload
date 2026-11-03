"""Извлечение чипа, погасшая киберголова и инерционное падение Капри."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPen

from capri.ui.chip_art import draw_chip, ease
from capri.ui.neural_head import draw_neural_head
from capri.ui.startup_scene import _color, _halo_image


def _fall_progress(seconds):
    return max(0.,min(1.,(seconds-1.02)/1.32))


def falling_avatar_rect(viewport, initial, seconds):
    """Конечная позиция рассчитывается от размера и положения текущего аватара."""
    u=_fall_progress(seconds)
    anticipation=math.sin(math.pi*ease((seconds-.68)/.3))*min(14.,initial.height()*.04)
    distance=max(initial.height(),viewport.bottom()-initial.top()+initial.height()*1.2+100)
    scale=initial.width()/340
    drift=45*scale*math.sin(u*math.pi/2)
    shake=math.sin(seconds*47)*1.5*scale if .84<seconds<1.04 else 0.
    return initial.translated(drift+shake,distance*u*u-anticipation)


def _avatar(p, viewport, image, initial, seconds):
    if image is None:
        return
    u=_fall_progress(seconds)
    rect=falling_avatar_rect(viewport,initial,seconds)
    p.save()
    p.setOpacity(1-ease((u-.92)/.08))
    pivot=QPointF(rect.center().x(),rect.top()+rect.height()*.56)
    p.translate(pivot)
    p.rotate(6*u+22*u*u)
    # Чуть отстающий силуэт сообщает скорость, не меняя позу персонажа.
    if .08<u<.88:
        p.save()
        p.setOpacity(.10*(1-u))
        p.drawImage(QRectF(rect.x()-pivot.x()-8*u,rect.y()-pivot.y()-22*u,rect.width(),rect.height()),image)
        p.restore()
    p.drawImage(QRectF(rect.x()-pivot.x(),rect.y()-pivot.y(),rect.width(),rect.height()),image)
    p.restore()


def paint_shutdown_scene(p, viewport, center, seconds, outgoing=None, outgoing_rect=None):
    t=max(0.,seconds)
    if t>=2.55:
        return
    background=ease(t/.24)*(1-ease((t-1.65)/.85))
    p.fillRect(viewport,_color("#06070c",235*background))
    radius=min(viewport.width(),viewport.height())*.58
    p.save()
    p.setOpacity(background*(1-ease((t-.75)/.7)))
    p.drawImage(QRectF(center.x()-radius,center.y()-radius,radius*2,radius*2),_halo_image())
    p.restore()
    scale=max(.45,min(viewport.width()/760,viewport.height()/620,1.75))
    extraction=ease((t-.26)/.64)
    power=1-ease((extraction-.2)/.62)
    head_alpha=ease(t/.20)*(1-ease((t-1.06)/.56))
    # Один чип, отделённый от головы: после извлечения она больше не тянет его за собой.
    p.save()
    p.setOpacity(ease(t/.20)*(1-ease((t-1.24)/.55)))
    p.translate(center)
    p.scale(scale,scale)
    p.translate(74+195*extraction,-71-18*extraction)
    p.rotate(10*extraction+12*ease((t-1.06)/.7))
    draw_chip(p,QRectF(0,-23,94,51))
    p.restore()
    p.save()
    p.translate(center+QPointF(0,12*ease((t-.94)/.6)*scale))
    p.scale(scale,scale)
    p.rotate(-5*ease((t-.96)/.62))
    p.setOpacity(head_alpha)
    # Пока чип в разъёме, его вставленный конец скрыт лицевой пластиной.
    draw_neural_head(p,power,.85,eye_focus=0.)
    # Контакт размыкается одним коротким световым импульсом.
    impact=max(0.,1-abs(t-.52)/.13)
    if impact:
        p.setPen(QPen(_color("#ffc1cf",150*impact),1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(99,-71),8+12*(1-impact),8+12*(1-impact))
    p.restore()
    p.save()
    p.setOpacity(ease(t/.25)*(1-ease((t-1.12)/.4)))
    p.translate(center)
    p.scale(scale,scale)
    font=QFont("Consolas");font.setPixelSize(10)
    p.setFont(font)
    p.setPen(_color("#a4a6af"))
    p.drawText(QRectF(-170,157,340,18),Qt.AlignmentFlag.AlignCenter,
               "CAPRI / CHIP REMOVED" if extraction>.97 else "CAPRI / DISCONNECTING")
    p.restore()
    if outgoing_rect is None:
        outgoing_rect=QRectF(center.x()-170,center.y()+30,340,380)
    _avatar(p,viewport,outgoing,outgoing_rect,t)
