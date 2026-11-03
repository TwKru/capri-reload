"""Общая киберголова для подключения и извлечения чипа."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen, QPolygonF

from capri.ui.chip_art import ease

EYE_CENTER = QPointF(27,-26)
IRIS_RADIUS = 8.


def _color(hex_value, alpha=255):
    color = QColor(hex_value)
    color.setAlpha(round(max(0,min(255,alpha))))
    return color


def _polygon(points):
    return QPolygonF([QPointF(x,y) for x,y in points])


def _face_outline():
    path = QPainterPath(QPointF(-88,-92))
    path.cubicTo(-91,-152,-43,-169,12,-158)
    path.cubicTo(54,-155,82,-127,87,-94)
    path.lineTo(91,-31)
    path.lineTo(72,-8)
    path.lineTo(59,48)
    path.lineTo(17,91)
    path.lineTo(-23,83)
    path.lineTo(-54,49)
    path.lineTo(-77,4)
    path.lineTo(-94,-29)
    path.closeSubpath()
    return path


def draw_neural_head(p, activation, seconds, eye_focus=0.):
    """Скульптурная маска в три четверти; цвет появляется лишь после контакта."""
    p.save()
    # Шея, кабели и затылочный каркас — позади белых лицевых пластин.
    p.setPen(QPen(_color("#747881"),1.8))
    p.setBrush(_color("#14151b"))
    p.drawPolygon(_polygon([(-40,49),(48,46),(52,109),(79,130),(-76,130),(-42,104)]))
    for x in (-31,-17,0,19,35):
        wire = QPainterPath(QPointF(x,64))
        wire.cubicTo(x-7,84,x+10,107,x+4,127)
        p.setPen(QPen(_color("#cacbd0" if x%2 else "#4b4e57"),2.6))
        p.drawPath(wire)
    p.setPen(QPen(_color("#dddfe4"),2))
    p.setBrush(_color("#1f2027"))
    p.drawEllipse(QRectF(58,-105,48,101))
    p.setPen(QPen(_color("#60636e"),1.2))
    for y in (-81,-65,-49,-33):
        p.drawLine(83,y,103,y-6)
    face = _face_outline()
    material = QLinearGradient(-90,-100,75,70)
    material.setColorAt(0,_color("#ffffff"))
    material.setColorAt(.45,_color("#b7bbc3"))
    material.setColorAt(.7,_color("#ebedf0"))
    material.setColorAt(1,_color("#606571"))
    p.setPen(QPen(_color("#edeff4"),2))
    p.setBrush(material)
    p.drawPath(face)
    # Крупные плоскости читаются и на небольшом экране.
    facets = (
        ("#f8f9fb",[(-70,-109),(-26,-144),(31,-138),(58,-106),(17,-77),(-46,-78)]),
        ("#737985",[(-83,-91),(-56,-113),(-43,-72),(-68,-34),(-84,-39)]),
        ("#d4d7dd",[(24,-133),(66,-108),(76,-68),(44,-47),(21,-77)]),
        ("#737a85",[(-69,-1),(-36,14),(-22,54),(-23,76),(-52,43)]),
        ("#f1f3f7",[(8,10),(51,-3),(44,33),(15,58),(-8,53)]),
        ("#3d424c",[(52,-1),(71,-16),(58,43),(20,82),(17,62),(43,34)]),
        ("#dfe2e7",[(-21,59),(11,64),(17,82),(-21,76),(-35,61)]),
    )
    p.setPen(Qt.PenStyle.NoPen)
    for color,points in facets:
        p.setBrush(_color(color))
        p.drawPolygon(_polygon(points))
    p.setPen(QPen(_color("#252933"),2))
    seams = (
        [(-65,-101),(-29,-113),(-14,-82),(-21,-53)],
        [(26,-134),(27,-104),(56,-88),(70,-57)],
        [(-73,-20),(-50,-9),(-38,17),(-24,26)],
        [(57,2),(31,15),(22,42),(5,51)],
        [(-40,49),(-22,59),(8,61),(28,47)],
    )
    for points in seams:
        p.drawPolyline(_polygon(points))
    # Глубокие глазницы и нос: без плоской «улыбки робота».
    p.setBrush(_color("#090b12"))
    p.setPen(QPen(_color("#777e8b"),1))
    p.drawPolygon(_polygon([(-65,-39),(-21,-29),(-31,-11),(-61,-17)]))
    p.drawPolygon(_polygon([(0,-28),(49,-44),(45,-18),(8,-8)]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(_polygon([(-16,-15),(-31,13),(-9,19),(-3,10)]))
    p.setBrush(_color("#eef1f5"))
    p.drawPolygon(_polygon([(-13,-18),(-15,9),(-7,13),(-3,7)]))
    p.setPen(QPen(_color("#2b303a"),3))
    p.drawPolyline(_polygon([(-31,38),(-12,34),(11,37),(27,30)]))
    p.setPen(QPen(_color("#edf0f4"),1.2))
    p.drawPolyline(_polygon([(-28,42),(-10,39),(10,42),(22,37)]))
    for x,y in ((-63,-73),(57,-98),(-49,32),(39,27)):
        p.setBrush(_color("#3c424e"))
        p.setPen(QPen(_color("#e0e4ea"),1))
        p.drawEllipse(QPointF(x,y),2.5,2.5)
    # Световой скан и активация встроены в материал, а не наложены на фон.
    p.save()
    p.setClipPath(face)
    scan_y = -160 + 270*ease((seconds-.18)/.85)
    p.setPen(QPen(_color("#ffffff",80*(1-activation)),1))
    p.drawLine(QPointF(-120,scan_y),QPointF(100,scan_y-28))
    if activation>0:
        for width,alpha in ((7,42),(2.2,240)):
            p.setPen(QPen(_color("#ff224c",alpha*activation),width))
            p.drawPolyline(_polygon([(-60,-27),(-35,-21),(-29,-24)]))
        # Красная линза — точная точка назначения камеры при подключении.
        p.setPen(QPen(_color("#ff9aae",170*activation*(1-eye_focus)),.8))
        p.setBrush(_color("#ff224c",255*activation))
        p.drawEllipse(EYE_CENTER,IRIS_RADIUS,IRIS_RADIUS)
        highlight=activation*(1-ease(eye_focus/.6))
        if highlight>0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_color("#ffe0e7",210*highlight))
            p.drawEllipse(EYE_CENTER+QPointF(-2.4,-3.6),1.1,1.1)
        p.setPen(QPen(_color("#ff224c",210*activation),1.6))
        p.drawPolyline(_polygon([(80,-72),(62,-66),(61,-48),(35,-42)]))
        p.drawPolyline(_polygon([(63,-5),(37,9),(29,32)]))
    p.restore()
    # Разъём маскирует вставленный конец чипа: ощущение реальной глубины.
    p.setPen(QPen(_color("#626772"),1.4))
    p.setBrush(_color("#080a10"))
    p.drawRoundedRect(QRectF(78,-91,21,43),3,3)
    p.setPen(QPen(_color("#ff224c" if activation else "#e1e4eb",100+155*activation),2))
    p.drawLine(99,-86,99,-53)
    p.restore()
