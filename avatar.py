"""Окно-аватар Капри: прозрачное, поверх всех окон, с глитч-эффектами,
вспышками и «лагами» при появлении, речи и исчезновении."""
import math
import json
import os
import random
import time
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, QPoint
from PySide6.QtGui import (QColor, QFont, QImage, QImageReader, QRegion, QPainter, QPainterPath, QPen,
                           QPolygonF, QGuiApplication, QStaticText, QTextOption, QTransform)
from PySide6.QtWidgets import QWidget

PINK = QColor(255, 34, 96)
PURPLE = QColor(150, 70, 255)
GREEN = QColor(40, 255, 150)
CYAN = QColor(0, 240, 255)
WHITE = QColor(255, 255, 255)
DARK = QColor(10, 6, 18)

W, H = 340, 500        # размер окна
FIG_H = 380            # высота области фигуры, ниже — HUD с субтитрами
APPEAR_FRAMES = 30
VANISH_FRAMES = 16

FMT = QImage.Format.Format_ARGB32_Premultiplied
AA = QPainter.RenderHint.Antialiasing
# Масштаб экрана Windows (125 % → 1.25). Все кадры рисуем в реальных пикселях экрана,
# иначе Windows растягивает картинку 340×500 и Капри с текстом мылятся. Ставит Avatar.
DPR = 1.0


def canvas(w, h):
    """Прозрачная картинка w×h логических пикселей с запасом под масштаб экрана."""
    img = QImage(round(w * DPR), round(h * DPR), FMT)
    img.setDevicePixelRatio(DPR)
    img.fill(Qt.GlobalColor.transparent)
    return img


def hidpi(src):
    """Картинку из файла подгоняем под масштаб экрана, сохраняя её логический размер."""
    if DPR != 1:
        src = src.scaled(round(src.width() * DPR), round(src.height() * DPR),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        src.setDevicePixelRatio(DPR)
    return src


def flip_horizontal(image):
    if hasattr(image, "flipped"):
        return image.flipped(Qt.Orientation.Horizontal)
    return image.mirrored(True, False)  # Qt < 6.9
CM = QPainter.CompositionMode

STATUS_TEXT = {
    "idle": "ОНЛАЙН",
    "listening": "СЛУШАЮ",
    "thinking": "ОБРАБОТКА",
    "speaking": "ПЕРЕДАЧА",
}


def _shard(cx, cy, ang, length, width, rnd, jag=6):
    """Рваный «осколок» от центра наружу."""
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    left, right = [], []
    for i in range(jag + 1):
        t = i / jag
        wdt = width * (1 - t) ** 0.8
        px, py = cx + dx * length * t, cy + dy * length * t
        jl, jr = rnd.uniform(0.4, 1.4), rnd.uniform(0.4, 1.4)
        left.append(QPointF(px + nx * wdt * jl, py + ny * wdt * jl))
        right.append(QPointF(px - nx * wdt * jr, py - ny * wdt * jr))
    tip = QPointF(cx + dx * length * 1.06, cy + dy * length * 1.06)
    return QPolygonF(left + [tip] + right[::-1])


def build_procedural(w, h):
    """Рисует фигуру Капри: тёмные осколки, розовые искрящиеся «крылья»
    с фиолетовым контуром и зелёный ромб, на котором потом рисуется глаз."""
    img = canvas(w, h)
    p = QPainter(img)
    p.setRenderHint(AA)
    rnd = random.Random(1337)
    cx, cy = w * 0.5, h * 0.47

    for _ in range(8):
        poly = _shard(cx, cy, rnd.uniform(0, 2 * math.pi), rnd.uniform(.32, .5) * h,
                      rnd.uniform(14, 28), rnd, 5)
        p.setPen(QPen(PURPLE, 2))
        p.setBrush(QColor(12, 8, 20, 235))
        p.drawPolygon(poly)

    pink = QPainterPath()
    pink.setFillRule(Qt.FillRule.WindingFill)
    for i in range(11):
        ang = -math.pi / 2 + (i - 5) * 0.27 + rnd.uniform(-.07, .07)
        pink.addPolygon(_shard(cx, cy, ang, rnd.uniform(.26, .45) * h, rnd.uniform(16, 30), rnd, 7))
    for i in range(5):
        ang = math.pi / 2 + (i - 2) * 0.38 + rnd.uniform(-.1, .1)
        pink.addPolygon(_shard(cx, cy, ang, rnd.uniform(.18, .32) * h, rnd.uniform(12, 20), rnd, 6))
    pink = pink.simplified()

    p.save()
    p.translate(5, 4)
    p.fillPath(pink, PURPLE)
    p.restore()
    p.fillPath(pink, PINK)

    p.save()
    p.setClipPath(pink)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(1100):
        r = rnd.choice([0.8, 1.2, 1.6, 2.4, 3.2])
        p.setBrush(QColor(255, rnd.randint(140, 230), rnd.randint(190, 255), rnd.randint(120, 255)))
        p.drawEllipse(QPointF(rnd.uniform(0, w), rnd.uniform(0, h)), r, r)
    p.restore()

    # зелёный ромб-символ за глазом
    d = 92
    diamond = QPolygonF([QPointF(cx - d * 1.35, cy), QPointF(cx, cy - d * 0.8),
                         QPointF(cx + d * 1.35, cy), QPointF(cx, cy + d * 0.8)])
    p.setPen(QPen(GREEN, 4))
    p.setBrush(QColor(8, 20, 16, 240))
    p.drawPolygon(diamond)
    p.end()
    return img, (cx, cy)


def draw_eye(p, cx, cy, open_=1.0, pupil=1.0, glow=1.0):
    r = 46
    almond = QPainterPath()
    almond.moveTo(cx - r * 1.5, cy)
    almond.quadTo(cx, cy - r * 1.25 * open_, cx + r * 1.5, cy)
    almond.quadTo(cx, cy + r * 1.25 * open_, cx - r * 1.5, cy)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(6, 0, -1):
        p.setPen(QPen(QColor(40, 255, 150, int(min(255, 16 * glow))), i * 5))
        p.drawPath(almond)
    p.setPen(QPen(GREEN, 5))
    p.setBrush(QColor(6, 24, 20))
    p.drawPath(almond)
    if open_ < 0.15:
        return
    p.save()
    p.setClipPath(almond)
    c = QPointF(cx, cy)
    p.setPen(QPen(GREEN, 4))
    p.setBrush(QColor(20, 40, 90))
    p.drawEllipse(c, r * .62 * pupil, r * .62 * pupil)
    p.setPen(QPen(QColor(120, 200, 255), 2))
    p.setBrush(QColor(4, 4, 14))
    p.drawEllipse(c, r * .3 * pupil, r * .3 * pupil)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(WHITE)
    p.drawEllipse(QPointF(cx - r * .14, cy - r * .14), 4, 4)
    p.restore()


def tinted(img, color):
    out = img.copy()
    p = QPainter(out)
    p.setCompositionMode(CM.CompositionMode_SourceIn)
    p.fillRect(out.rect(), color)
    p.end()
    return out


def load_custom(path, w, h):
    src = QImage(path)
    if src.isNull():
        return None
    src = src.scaled(round(w * DPR), round(h * DPR), Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    src.setDevicePixelRatio(DPR)
    size = src.deviceIndependentSize()
    img = canvas(w, h)
    p = QPainter(img)
    p.drawImage(QPointF((w - size.width()) / 2, h - size.height()), src)
    p.end()
    return img


ANIM_FPS = 24
WALK_SPEED = 140          # пикселей по экрану в секунду
WALK_ANIMATION_SPEED = 0.65  # темп шага независимо от скорости перемещения
TELE_OUT_FRAMES = 5      # сколько кадров Капри «сжимается» перед телепортом
BOLT_MS = 380            # сколько живёт молния


def bolt_path(a, b, rnd, detail=5, spread=0.24):
    """Ломаная молния из a в b: рекурсивно сдвигаем середины отрезков вбок."""
    pts = [a, b]
    spread = math.hypot(b.x() - a.x(), b.y() - a.y()) * spread
    for _ in range(detail):
        nxt = [pts[0]]
        for p, q in zip(pts, pts[1:]):
            mx, my = (p.x() + q.x()) / 2, (p.y() + q.y()) / 2
            dx, dy = q.x() - p.x(), q.y() - p.y()
            ln = math.hypot(dx, dy) or 1
            off = rnd.uniform(-spread, spread)
            nxt += [QPointF(mx - dy / ln * off, my + dx / ln * off), q]
        pts = nxt
        spread *= 0.55
    return pts


def zigzag_path(a, b, rnd):
    """Классический мультяшный «⚡»: несколько крупных изломов поочерёдно в разные стороны."""
    n = rnd.randint(4, 7)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln, dx / ln
    amp = min(90.0, ln * 0.12)
    pts = [a]
    for i in range(1, n):
        t = i / n + rnd.uniform(-0.3, 0.3) / n
        side = (1 if i % 2 else -1) * amp * rnd.uniform(0.6, 1.3)
        pts.append(QPointF(a.x() + dx * t + nx * side, a.y() + dy * t + ny * side))
    pts.append(b)
    dense = [pts[0]]  # дробим отрезки, чтобы у ленты были рваные края и утолщение
    for p, q in zip(pts, pts[1:]):
        for j in range(1, 6):
            s = j / 5
            dense.append(QPointF(p.x() + (q.x() - p.x()) * s + rnd.uniform(-2, 2),
                                 p.y() + (q.y() - p.y()) * s + rnd.uniform(-2, 2)))
    return dense


def ribbon(pts, width, rnd, jitter=0.4):
    """Плоская лента-полигон вдоль ломаной: толще в середине, острая на концах, с рваной шириной."""
    n = len(pts)
    left, right = [], []
    for i, pt in enumerate(pts):
        t = i / (n - 1)
        a, b = pts[max(0, i - 1)], pts[min(n - 1, i + 1)]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        w = (width * math.sin(math.pi * t) ** 0.6 + 1) / 2
        wl, wr = w * rnd.uniform(1 - jitter, 1 + jitter), w * rnd.uniform(1 - jitter, 1 + jitter)
        left.append(QPointF(pt.x() + nx * wl, pt.y() + ny * wl))
        right.append(QPointF(pt.x() - nx * wr, pt.y() - ny * wr))
    return QPolygonF(left + right[::-1])


def burst(c, rnd, outer):
    """Плоская рваная «звезда» вспышки."""
    spikes = rnd.randint(7, 11)
    rot = rnd.uniform(0, math.pi)
    pts = []
    for i in range(spikes * 2):
        r = outer * rnd.uniform(0.7, 1.15) if i % 2 == 0 else outer * rnd.uniform(0.25, 0.4)
        ang = rot + math.pi * i / spikes
        pts.append(QPointF(c.x() + math.cos(ang) * r, c.y() + math.sin(ang) * r))
    return QPolygonF(pts)


BOLT_STYLES = ("jagged", "zigzag", "twin", "forked", "broken")


class LightningOverlay(QWidget):
    """Прозрачное окно на весь экран, сквозь которое проходят клики. Показывается только на время
    удара молнии. Молния плоская, мультяшная: залитые полигоны без свечения, с фиолетовой тенью.
    Каждый удар — случайный стиль (рваная, «⚡»-зигзаг, двойная, ветвистая, разорванная на куски)
    и случайные акценты (белая сердцевина, зелёная полоска, искры)."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.a = self.b = QPointF()
        self.start = 0.0
        self.polys, self.bursts = [], []
        self.style, self.width = "jagged", 10.0
        self.white_core = self.green_accent = self.sparks = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def strike(self, a, b):
        """a, b — глобальные координаты экрана."""
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        self.a = QPointF(a - geo.topLeft())
        self.b = QPointF(b - geo.topLeft())
        self.start = time.time()
        rnd = random.Random()
        self.style = rnd.choice(BOLT_STYLES)
        self.width = rnd.uniform(7, 13)
        self.white_core = rnd.random() < 0.35
        self.green_accent = rnd.random() < 0.3
        self.sparks = rnd.random() < 0.6
        self._regen()
        self.show()
        self.raise_()
        self.timer.start(16)

    def _regen(self):
        """Новая геометрия в рамках выбранного стиля (молния мерцает и меняет форму)."""
        rnd = random.Random()
        a, b, w = self.a, self.b, self.width
        if self.style == "zigzag":
            main = zigzag_path(a, b, rnd)
        else:
            main = bolt_path(a, b, rnd, detail=4 if self.style == "broken" else 5,
                             spread=0.3 if self.style == "forked" else 0.22)
        polys = []  # (полигон, точки для искр, масштаб толщины)
        if self.style == "twin":
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy) or 1
            off = QPointF(-dy / ln * rnd.uniform(9, 16), dx / ln * rnd.uniform(9, 16))
            second = bolt_path(a + off, b + off, rnd, 5, 0.18)
            polys += [(ribbon(main, w * 0.8, rnd), main, 0.8), (ribbon(second, w * 0.55, rnd), second, 0.55)]
        elif self.style == "broken":
            k = 0
            while k < len(main) - 2:  # куски с разрывами, слегка сдвинутые — «глитчевая» молния
                seg = main[k:k + rnd.randint(5, 9)]
                shift = QPointF(rnd.uniform(-6, 6), rnd.uniform(-6, 6))
                seg = [q + shift for q in seg]
                if len(seg) >= 2:
                    polys.append((ribbon(seg, w * rnd.uniform(0.8, 1.3), rnd), seg, 1.0))
                k += len(seg) - 1  # куски стыкуются почти встык, разрыв — только сдвиг
        else:
            polys.append((ribbon(main, w * (1.6 if self.style == "zigzag" else 1.0), rnd, 0.25
                                 if self.style == "zigzag" else 0.4), main, 1.0))
        branches = {"forked": (3, 6), "jagged": (1, 3), "zigzag": (0, 1)}.get(self.style, (0, 2))
        base_ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        for _ in range(rnd.randint(*branches)):
            p = main[rnd.randrange(len(main) // 5, max(len(main) // 5 + 1, len(main) * 4 // 5))]
            ang = base_ang + rnd.choice((-1, 1)) * rnd.uniform(0.4, 1.3)
            ln = rnd.uniform(30, 110)
            br = bolt_path(p, QPointF(p.x() + math.cos(ang) * ln, p.y() + math.sin(ang) * ln), rnd, 3)
            polys.append((ribbon(br, w * 0.5, rnd), br, 0.5))
        self.polys = polys
        self.bursts = [(burst(a, rnd, rnd.uniform(14, 22)), a), (burst(b, rnd, rnd.uniform(20, 32)), b)]

    def _tick(self):
        el = (time.time() - self.start) * 1000
        if el > BOLT_MS:
            self.timer.stop()
            self.hide()
            return
        if random.random() < 0.45:  # мерцание формы разряда
            self._regen()
        self.update()

    def paintEvent(self, _):
        el = (time.time() - self.start) * 1000
        # плоско, без плавного затухания: в конце молния просто «моргает» и пропадает
        if el > BOLT_MS * 0.65 and int(el / 45) % 2:
            return
        p = QPainter(self)
        p.setRenderHint(AA)
        p.setPen(Qt.PenStyle.NoPen)
        shadow = QPointF(4, 3)
        for poly, _, _ in self.polys:      # фиолетовая тень под всем
            p.setBrush(PURPLE)
            p.drawPolygon(poly.translated(shadow))
        for poly, _, _ in self.polys:
            p.setBrush(PINK)
            p.drawPolygon(poly)
        for poly, c in self.bursts:
            p.setBrush(PURPLE)
            p.drawPolygon(poly.translated(shadow))
            p.setBrush(PINK)
            p.drawPolygon(poly)
            p.setBrush(WHITE)
            p.drawPolygon(QPolygonF([c + (q - c) * 0.35 for q in poly]))

        rnd = random.Random()
        for poly, pts, scale in self.polys:
            if self.green_accent and scale >= 0.8:  # тонкая зелёная полоска вдоль разряда
                p.setBrush(GREEN)
                p.drawPolygon(ribbon([q + QPointF(0, -self.width * 0.55) for q in pts],
                                     self.width * 0.22, rnd, 0.6))
            if self.white_core and scale >= 0.8:
                p.setBrush(WHITE)
                p.drawPolygon(ribbon(pts, self.width * 0.28 * scale, rnd, 0.5))
            if self.sparks:
                p.save()
                p.setClipRegion(QRegion(poly.toPolygon()))
                p.setBrush(QColor(255, 225, 240))
                for q in pts[::2]:
                    if rnd.random() < 0.5:
                        r = rnd.choice([1.0, 1.5, 2.2])
                        p.drawEllipse(QPointF(q.x() + rnd.uniform(-3, 3), q.y() + rnd.uniform(-3, 3)), r, r)
                p.restore()
        p.end()


class AnimationFrames:
    """PNG декодируются по требованию; в памяти остаётся не более восьми кадров на анимацию."""
    CACHE_SIZE = 8

    def __init__(self, files, mirror_keys=()):
        self.files = tuple(files)
        self.cache = OrderedDict()
        self.mirror_keys = frozenset(mirror_keys)

    def __len__(self):
        return len(self.files)

    def __getitem__(self, index):
        if not -len(self.files) <= index < len(self.files):
            raise IndexError(index)
        index %= len(self.files)
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        src = hidpi(QImage(self.files[index]))
        if index in self.mirror_keys:
            src = flip_horizontal(src)
        img = canvas(W, FIG_H)
        p = QPainter(img)
        sw, sh = src.deviceIndependentSize().width(), src.deviceIndependentSize().height()
        y = FIG_H - sh if sh >= FIG_H * 0.9 else (FIG_H - sh) // 2
        p.drawImage(QPointF((W - sw) // 2, y), src)
        p.end()
        self.cache[index] = img
        while len(self.cache) > self.CACHE_SIZE:
            self.cache.popitem(last=False)
        return img


class SmoothAnimationFrames:
    """Плавные промежуточные кадры считаются при воспроизведении, с ограниченным кэшем."""
    def __init__(self, keys, steps=6, fps=60):
        self.keys, self.steps, self.fps = keys, steps, fps
        self.cache = OrderedDict()

    def __len__(self):
        return len(self.keys) * self.steps

    def __getitem__(self, index):
        if not -len(self) <= index < len(self):
            raise IndexError(index)
        index %= len(self)
        key, part = divmod(index, self.steps)
        if part == 0:
            return self.keys[key]
        if index not in self.cache:
            frame = canvas(W, FIG_H)
            painter = QPainter(frame)
            painter.setOpacity(1 - part / self.steps)
            painter.drawImage(0, 0, self.keys[key])
            painter.setCompositionMode(CM.CompositionMode_Plus)
            painter.setOpacity(part / self.steps)
            painter.drawImage(0, 0, self.keys[(key + 1) % len(self.keys)])
            painter.end()
            self.cache[index] = frame
            if len(self.cache) > 8:
                self.cache.popitem(last=False)
        self.cache.move_to_end(index)
        return self.cache[index]


class SpriteStripFrames:
    """Lazy sprite strips: one decoded strip and eight rendered frames shared by all clips."""
    strips = OrderedDict()
    cache = OrderedDict()

    def __init__(self, path, count, fps):
        self.path, self.count, self.fps = path, count, fps

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if not -self.count <= index < self.count:
            raise IndexError(index)
        index %= self.count
        key = self.path, index, DPR
        if key not in self.cache:
            if self.path not in self.strips:
                self.strips.clear()
                self.strips[self.path] = QImage(self.path)
            strip = self.strips[self.path]
            width = strip.width() // self.count
            src = strip.copy(index * width, 0, width, strip.height())
            src = src.scaled(round(W * DPR), round(FIG_H * DPR), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            src.setDevicePixelRatio(DPR)
            frame = canvas(W, FIG_H)
            painter = QPainter(frame)
            size = src.deviceIndependentSize()
            painter.drawImage(QPointF((W - size.width()) / 2, FIG_H - size.height()), src)
            painter.end()
            self.cache[key] = frame
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]


def load_desktop_anims(folder):
    clips = {"idle": ("idle", 16, 8), "blink": ("blink", 4, 8), "grin": ("grin", 16, 8),
             "drag": ("dangle", 24, 10), "sleep": ("sleep", 16, 6), "wake": ("wake", 13, 15),
             "dance": ("dance", 16, 12)}
    result = {}
    for name, (file, count, fps) in clips.items():
        path = os.path.join(folder, file + ".png")
        reader = QImageReader(path)
        size = reader.size()
        if reader.canRead() and size.width() > 0 and size.width() % count == 0 and size.height() > 0:
            result["desktop_" + name] = SpriteStripFrames(path, count, fps)
    return result


def load_anims(anim_dir):
    """assets/anim/<имя>/*.png → {имя: [кадры размером W×FIG_H]}. Кадры делает tools/convert_anim.py."""
    anims = {}
    if not os.path.isdir(anim_dir):
        return anims
    for name in sorted(os.listdir(anim_dir)):
        folder = os.path.join(anim_dir, name)
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png")) if os.path.isdir(folder) else []
        try:
            with open(os.path.join(folder, "motion.json"), encoding="utf-8") as file:
                motion = json.load(file)
        except (OSError, ValueError):
            motion = {}
        if not isinstance(motion, dict):
            motion = {}
        mirrors = motion.get("mirror_keys", [])
        frames = AnimationFrames([os.path.join(folder, f) for f in files
                                  if QImageReader(os.path.join(folder, f)).canRead()],
                                 mirrors if isinstance(mirrors, list) and all(type(i) is int for i in mirrors) else ())
        if frames:
            steps, fps = motion.get("inbetweens", 1), motion.get("fps", ANIM_FPS)
            if type(steps) is int and 1 < steps <= 8 and type(fps) is int and 1 <= fps <= 60:
                frames = SmoothAnimationFrames(frames, steps, fps)
            anims[name] = frames
    return anims


class Avatar(QWidget):
    clicked = Signal()
    petted = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, assets_dir):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.setMouseTracking(True)
        global DPR
        DPR = max([s.devicePixelRatio() for s in QGuiApplication.screens()] or [1.0])

        # Позы: все картинки из assets/poses (и, для совместимости, assets/capri.png).
        # Они периодически сменяют друг друга, чтобы Капри не стояла статичной картинкой.
        pose_dir = os.path.join(assets_dir, "poses")
        pose_files = []
        for folder in (assets_dir, pose_dir):
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                low = name.lower()
                if folder == assets_dir and low not in ("capri.png", "capri.jpg", "capri.webp"):
                    continue
                if low.endswith((".png", ".webp", ".jpg")) and low not in [os.path.basename(f).lower()
                                                                            for f in pose_files]:
                    pose_files.append(os.path.join(folder, name))
        self.poses = [img for img in (load_custom(f, W, FIG_H) for f in pose_files) if img is not None]
        if self.poses:
            self.base, self.eye_pos = self.poses[0], None
        else:  # картинок нет — рисованная Капри с глазом
            self.base, self.eye_pos = build_procedural(W, FIG_H)
            self.poses = [self.base]

        # поза для прогулок: capri_roam.png в assets или в poses
        self.roam_img = None
        for path in (os.path.join(assets_dir, "capri_roam.png"), os.path.join(pose_dir, "capri_roam.png")):
            if os.path.exists(path):
                self.roam_img = load_custom(path, W, FIG_H)
                break
        self.pose_idx = 0
        self.next_pose = 0.0
        self.roaming = False
        self.roam_x = 0.0
        self.roam_dir = -1
        self.roam_last = 0.0
        self.walk_time = 0.0
        self.next_spin = time.time() + random.uniform(5, 10)
        self.home_pos = None

        self.overlay = LightningOverlay()
        self.tele_target = None      # куда телепортируемся (QPoint), пока идёт «сжатие»
        self.tele_k = 0
        self.hopping = False         # прыгает по экрану, пока отвечает
        self.hop_home = None
        self.next_hop = 0.0
        self.on_teleport = None      # звук телепорта (ставит main)

        self.anims = load_anims(os.path.join(assets_dir, "anim"))
        self.anims.update(load_desktop_anims(os.path.join(assets_dir, "desktop_sprites")))
        self.idle_started = time.time()
        self.next_blink = time.time() + random.uniform(3, 7)
        self.sleeping = False
        self.dance_until = 0.0
        self._drag_started = 0.0
        self._press_origin = None
        self._pat_x = None
        self._pat_direction = 0
        self._pat_turns = []
        self._last_pat = 0.0
        self.anim = None             # имя проигрываемой анимации
        self.anim_start = 0.0
        self.anim_loop = False

        self.frame = canvas(W, H)
        self._scanlines = canvas(W, FIG_H)
        scan = QPainter(self._scanlines)
        scan.setRenderHint(AA)
        scan.setPen(QPen(QColor(0, 0, 0, 80), 1))
        for y in range(0, FIG_H, 3):
            scan.drawLine(0, y, W, y)
        scan.end()
        self.state = "hidden"       # hidden / appearing / visible / vanishing
        self.mode = "idle"           # idle / listening / thinking / speaking
        self.mood = "neutral"
        self.mode_until = 0.0
        self.hide_at = 0.0
        self.hide_after = 12.0
        self.subtitle = ""
        self._subtitle_key = None
        self._subtitle_static = None
        self._tint_cache = OrderedDict()
        self.k = 0                   # кадров в текущей фазе
        self.t = 0
        self.burst = 0
        self.burst_level = 0.0
        self.lag = 0
        self.blink = 0
        self.user_moved = False
        self.game_mode = False
        self._press = None
        self._moved = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    # ---------- управление ----------
    def set_game_mode(self, active):
        self.game_mode = bool(active)
        if self.game_mode:
            self.overlay.timer.stop()
            self.overlay.hide()
            self.hopping = False
            self.tele_target = self.hop_home = None
            self.lag = self.burst = 0
            if self.timer.isActive():
                self.timer.setInterval(33)

    def start_roam(self):
        self.wake_up()
        """Прогулка: Капри появляется у одного края экрана и идёт вдоль панели задач к другому."""
        if self.roam_img is None and "walk" not in self.anims:
            return
        self.anim = None
        self.lag = self.burst = 0
        self.timer.start(33 if self.game_mode else 16)
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.home_pos = self.pos() if self.user_moved else QPoint(geo.left() + 24, geo.bottom() - H)
        self.roam_dir = random.choice((-1, 1))
        self.roam_x = geo.right() - W if self.roam_dir < 0 else geo.left()
        self.roam_last = time.time()
        self.walk_time = 0.0
        self.roaming = True
        self.move(int(self.roam_x), geo.bottom() - H)
        self.state, self.k = "appearing", 0
        self.hide_at = 0
        self.show()
        self.raise_()

    def stop_roam(self):
        """Прервать прогулку (позвали или кликнули): возвращаемся на обычное место."""
        if not self.roaming:
            return
        self.roaming = False
        self.move(self.home_pos if self.home_pos else self._random_spot())
        self.burst, self.burst_level = 6, 1.0

    def stop_motion(self):
        self.stop_roam()
        self.sleeping = False
        self.dance_until = 0.0
        self.anim = None
        self.lag = self.burst = 0

    def _roam_step(self, now):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        dt = min(0.1, now - self.roam_last)
        self.roam_last = now
        if self.state != "visible":
            return
        self.walk_time += dt * WALK_ANIMATION_SPEED
        self.roam_x += self.roam_dir * WALK_SPEED * dt
        lo, hi = geo.left() - 40, geo.right() - W + 40
        if not lo <= self.roam_x <= hi:
            if self.mode in ("thinking", "speaking"):
                self.roam_x = max(lo, min(hi, self.roam_x))  # договорит у края, потом уйдёт
            else:
                self.vanish()
        self.move(int(self.roam_x), geo.bottom() - H)

    # ---------- телепорт молнией ----------
    def teleport(self, target):
        if self.game_mode:
            self.move(target)
            return
        if self.state == "visible" and self.tele_target is None and not self.roaming:
            self.tele_target, self.tele_k = target, 0

    def move_to_named(self, where):
        """Переместиться по команде («в левый нижний угол», «в центр», «в другую сторону») молнией."""
        geo = QGuiApplication.primaryScreen().availableGeometry()
        m = 24
        xs = {"left": geo.left() + m, "right": geo.right() - W - m, "": self.x()}
        ys = {"top": geo.top() + m, "bottom": geo.bottom() - H - m, "": self.y()}
        if where == "center":
            target = QPoint(geo.center().x() - W // 2, geo.center().y() - H // 2)
        elif where == "other":  # зеркально через центр экрана
            target = QPoint(geo.left() + geo.right() - W - self.x(), self.y())
        else:
            v, _, h = where.partition("-") if "-" in where else (
                (where, "", "") if where in ("top", "bottom") else ("", "", where))
            target = QPoint(xs.get(h, self.x()), ys.get(v, self.y()))
        target.setX(max(geo.left(), min(geo.right() - W, target.x())))
        target.setY(max(geo.top(), min(geo.bottom() - H, target.y())))
        self.hopping, self.hop_home = False, None
        if self.state == "visible" and not self.roaming:
            self.teleport(target)
        else:
            self.move(target)

    def start_hopping(self):
        """Пока Капри отвечает, она скачет по экрану красной молнией."""
        if self.game_mode or self.roaming:
            return
        if self.hop_home is None:
            self.hop_home = self.pos()
        self.hopping = True
        self.next_hop = time.time() + 0.6

    def _random_spot(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        spot = self.pos()
        for _ in range(12):
            spot = QPoint(random.randint(geo.left(), geo.right() - W), random.randint(geo.top(), geo.bottom() - H))
            if math.hypot(spot.x() - self.x(), spot.y() - self.y()) > 350:
                break
        return spot

    def _tele_step(self, now):
        """Возвращает True, если этот тик занят телепортом."""
        if self.tele_target is not None:
            self.tele_k += 1
            if self.tele_k >= TELE_OUT_FRAMES:
                a = self.geometry().center()
                self.move(self.tele_target)
                self.overlay.strike(a, self.geometry().center())
                if self.on_teleport:
                    self.on_teleport()
                self.tele_target = None
                self.state, self.k = "appearing", APPEAR_FRAMES - 12
            return True
        if self.state != "visible":
            return False
        if self.hopping and self.mode == "speaking" and now > self.next_hop:
            self.teleport(self._random_spot())
            self.next_hop = now + random.uniform(1.6, 3.0)
        elif not self.hopping and self.hop_home is not None:
            if self.pos() != self.hop_home:
                self.teleport(self.hop_home)  # договорила — молнией домой
            else:
                self.hop_home = None
        return self.tele_target is not None

    def change_pose(self, idx=None):
        """Сменить позу с глитч-вспышкой. Без idx — любая другая."""
        if len(self.poses) < 2:
            return
        if idx is None:
            idx = random.choice([i for i in range(len(self.poses)) if i != self.pose_idx])
        self.pose_idx = idx
        self.base = self.poses[idx]
        self.burst, self.burst_level = random.randint(5, 9), 1.0
        self.next_pose = time.time() + random.uniform(12, 30)

    def summon(self):
        self.wake_up()
        self.timer.start(33)
        self.stop_roam()
        if self.state in ("visible", "appearing"):
            if not self.isVisible():
                self.show()
                self.raise_()
            self.burst, self.burst_level = 6, 0.9
            return
        if len(self.poses) > 1:  # каждое появление — в случайной позе
            self.change_pose(random.randrange(len(self.poses)))
        if not self.user_moved:
            self.move_to_named("bottom-left")  # появляемся слева снизу, над панелью задач
        self.state, self.k = "appearing", 0
        self.next_spin = time.time() + (random.uniform(5, 9) if random.random() < .4 else random.uniform(25, 60))
        self.hide_at = 0
        self.show()
        self.raise_()

    def vanish(self):
        if self.state in ("visible", "appearing"):
            self.state, self.k = "vanishing", 0

    def wake_up(self):
        if self.sleeping:
            self.sleeping = False
            self.hide_at = time.time() + self.hide_after
            self.play_anim("desktop_wake")

    def play_anim(self, name, loop=False):
        if name in ("sleep", "wake", "dance"):
            name = "desktop_" + name
        if name == "desktop_sleep":
            self.stop_roam()
            self.sleeping = True
            self.hopping, self.hop_home, self.tele_target = False, None, None
            self.hide_at = 0
            loop = True
        elif name == "desktop_wake":
            self.sleeping = False
        elif name == "desktop_dance":
            self.dance_until = time.time() + 12
            loop = True
        if name in self.anims:
            self.anim, self.anim_start, self.anim_loop = name, time.time(), loop
            self.lag = self.burst = 0

    def set_mode(self, mode, seconds=0.0):
        if mode != "idle":
            self.wake_up()
        if mode == "thinking" and self.mode != "thinking" and not self.roaming and self.anim != "desktop_wake":
            self.play_anim("eyes", loop=True)
        elif mode != "thinking" and self.anim == "eyes":
            self.anim = None
        if mode != "speaking":
            self.hopping = False
        self.mode = mode
        self.mode_until = time.time() + seconds if seconds > 0 else 0
        self.hide_at = max(time.time() + self.hide_after, self.dance_until + .5) if mode == "idle" and not self.sleeping else 0
        self.burst, self.burst_level = random.randint(3, 6), random.uniform(.4, .9)

    def set_subtitle(self, text):
        self.subtitle = text or ""

    def set_mood(self, mood):
        if mood not in ("neutral", "hurt", "happy", "playful", "bored"):
            mood = "neutral"
        self.mood = mood
        if self.isVisible():
            self.update()

    # ---------- анимация ----------
    def tick(self):
        interval = (166 if self.sleeping and self.mode == "idle" and self._press is None else
                    16 if not self.game_mode and (self.roaming or self.anim in ("spin", "walk")) else 33)
        self.timer.setInterval(interval)
        self.t += 1
        self.k += interval / 33
        now = time.time()
        if self.state == "appearing" and self.k >= APPEAR_FRAMES:
            self.state, self.k = "visible", 0
        elif self.state == "vanishing" and self.k >= VANISH_FRAMES:
            self.state = "hidden"
            self.timer.stop()
            self.hide()
            self.hopping, self.tele_target = False, None
            if self.hop_home is not None:
                self.move(self.hop_home)
                self.hop_home = None
            if self.roaming:
                self.roaming = False
                if self.home_pos:
                    self.move(self.home_pos)
            return
        if self.state == "hidden":
            self.timer.stop()
            return
        if self.anim == "desktop_dance" and now > self.dance_until:
            self.anim = None
        if self.mode_until and now > self.mode_until:
            self.set_mode("idle")
        if self.roaming:
            self._roam_step(now)
        elif self._tele_step(now):
            self.render()
            self.update()
            return
        elif (self.state == "visible" and self.mode == "idle" and not self.sleeping and self._press is None
              and self.anim is None and not self.game_mode and "desktop_blink" in self.anims and now >= self.next_blink):
            self.play_anim("desktop_blink")
            self.next_blink = now + random.uniform(3, 7)
        elif (self.state == "visible" and self.mode == "idle" and not self.sleeping and self._press is None and self.anim is None and
              not self.game_mode and "spin" in self.anims and now >= self.next_spin):
            self.play_anim("spin")
            self.next_spin = now + random.uniform(25, 60)
        elif (self.state == "visible" and self.next_pose and now > self.next_pose and self.anim is None
              and self.mode != "thinking" and not self.sleeping and "desktop_idle" not in self.anims):
            self.change_pose()
        elif self.state == "visible" and self.hide_at and now > self.hide_at:
            self.vanish()

        # «лаг»: кадр замирает на несколько тиков
        smooth = self.game_mode or self.roaming or "desktop_idle" in self.anims or self.anim in ("spin", "walk")
        if not smooth and self.lag > 0 and self.state != "vanishing":
            self.lag -= 1
            return
        lag_p = {"appearing": .12, "vanishing": 0}.get(self.state, .05 if self.mode == "speaking" else .015)
        if not smooth and random.random() < lag_p:
            self.lag = random.randint(2, 6)
        self.render()
        self.update()

    def _figure(self):
        if self._press is not None and self._moved and "desktop_drag" in self.anims:
            frames = self.anims["desktop_drag"]
            return frames[int((time.time() - self._drag_started) * frames.fps) % len(frames)]
        if self.roaming and "walk" in self.anims:
            frames = self.anims["walk"]
            index = int(self.walk_time * getattr(frames, "fps", ANIM_FPS)) % len(frames)
            frame = frames[index]
            return flip_horizontal(frame) if self.roam_dir < 0 else frame
        if self.anim:
            frames = self.anims[self.anim]
            idx = int((time.time() - self.anim_start) * getattr(frames, "fps", ANIM_FPS))
            if idx < len(frames) or self.anim_loop:
                return frames[idx % len(frames)]
            self.anim = None
        if self.roaming and self.roam_img is not None:
            return self.roam_img
        if "desktop_idle" in self.anims:
            frames = self.anims["desktop_idle"]
            index = 0 if self.game_mode else int((time.time() - self.idle_started) * frames.fps) % len(frames)
            return frames[index]
        if self.eye_pos is None:
            return self.base
        fig = self.base.copy()
        p = QPainter(fig)
        p.setRenderHint(AA)
        cx, cy = self.eye_pos
        open_, pupil, glow = 1.0, 1.0, 1.0
        if self.blink > 0:
            self.blink -= 1
            open_ = 0.08
        elif self.mode == "idle" and random.random() < 0.012:
            self.blink = 3
        if self.mode == "listening":
            glow = 1.6 + 0.8 * math.sin(self.t * 0.25)
            pupil = 1.12
        elif self.mode == "thinking":
            pupil = 0.7
        elif self.mode == "speaking":
            pupil = 0.8 + 0.35 * random.random()
            glow = 1.3 + random.random()
        draw_eye(p, cx, cy, open_, pupil, glow)

        if self.mode == "thinking":
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i, rad in enumerate((96, 116)):
                p.setPen(QPen(GREEN if i == 0 else CYAN, 3))
                a = (self.t * (9 if i == 0 else -6)) % 360
                rect = QRectF(cx - rad, cy - rad * .7, rad * 2, rad * 1.4)
                p.drawArc(rect, int(a * 16), 80 * 16)
                p.drawArc(rect, int((a + 180) * 16), 80 * 16)
        elif self.mode == "listening":
            ph = (self.t % 30) / 30
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(40, 255, 150, int(220 * (1 - ph))), 3))
            rad = 80 + 60 * ph
            p.drawEllipse(QPointF(cx, cy), rad * 1.3, rad * .85)
        p.end()
        return fig

    def render(self):
        f = self.frame
        f.fill(Qt.GlobalColor.transparent)
        p = QPainter(f)
        p.setRenderHint(AA)
        if self.roaming:
            p.translate(0, H - FIG_H)  # фигура внизу, место сверху — под окно с текстом
        glitch = 0.0
        flash = False
        yscale = 1.0
        xscale = 1.0

        if self.game_mode:
            if self.state == "appearing":
                p.setOpacity(min(1.0, self.k / APPEAR_FRAMES))
            elif self.state == "vanishing":
                p.setOpacity(max(0.0, 1 - self.k / VANISH_FRAMES))
        elif self.tele_target is not None:
            # перед телепортом сжимается в узкую красную вспышку
            glitch, flash = 1.0, True
            xscale = max(0.04, 1 - self.tele_k / TELE_OUT_FRAMES)
        elif self.state == "appearing":
            prog = self.k / APPEAR_FRAMES
            if self.k < 4:  # включение как у ЭЛТ: растущая линия
                self._crt_line(p, W * (self.k + 1) / 4, 3)
                p.end()
                return
            r = random.random()
            if r < 0.25 * (1 - prog):
                p.end()            # пропущенный кадр — мерцание
                return
            flash = r < 0.42 * (1 - prog)
            glitch = 1.0 - prog * 0.8
        elif self.state == "vanishing":
            prog = self.k / VANISH_FRAMES
            if prog > 0.55:
                q = (prog - 0.55) / 0.45
                self._crt_line(p, W * (1 - q) + 4, max(1, 6 * (1 - q)))
                p.end()
                return
            glitch = 1.0
            yscale = max(0.03, 1 - prog / 0.55)
            flash = random.random() < 0.3
        elif not (self.roaming or self.anim in ("spin", "walk")):
            if self.burst > 0:
                self.burst -= 1
                glitch = self.burst_level
            else:
                chance = {"speaking": .12, "thinking": .07, "listening": .04}.get(self.mode, .025)
                if random.random() < chance:
                    self.burst = random.randint(2, 7)
                    self.burst_level = random.uniform(.3, 1.0)
            if self.mode == "speaking":
                glitch = max(glitch, .08)

        fig = self._figure()
        ox = oy = 0
        if glitch > 0 and random.random() < glitch * 0.6:
            ox = random.randint(-int(14 * glitch), int(14 * glitch))
            oy = random.randint(-int(6 * glitch), int(6 * glitch))

        p.save()
        if yscale < 1 or xscale < 1:
            p.translate(W / 2, FIG_H / 2)
            p.scale((1 + (1 - yscale) * 0.4) * xscale, yscale * (1 + (1 - xscale) * 0.3))
            p.translate(-W / 2, -FIG_H / 2)

        split = int(2 + 12 * glitch) if glitch > 0.1 else (1 if self.mode == "speaking" else 0)
        if split:
            p.setOpacity(0.55)
            p.drawImage(ox - split, oy, self._tinted(fig, QColor(255, 0, 60)))
            p.drawImage(ox + split, oy + (1 if glitch > .5 else 0), self._tinted(fig, CYAN))
            p.setOpacity(1.0)

        if glitch > 0.15:
            y = 0
            while y < FIG_H:
                hgt = random.randint(4, 40)
                sx = random.randint(-int(44 * glitch), int(44 * glitch)) if random.random() < glitch * .7 else 0
                p.drawImage(QPointF(ox + sx, oy + y), fig, QRectF(0, y * DPR, W * DPR, hgt * DPR))
                y += hgt
        else:
            p.drawImage(ox, oy, fig)

        if flash:
            p.setOpacity(random.uniform(.5, .95))
            p.drawImage(ox, oy, self._tinted(fig, WHITE if random.random() < .5 else PINK))
            p.setOpacity(1.0)
        p.restore()

        if glitch > 0.3:
            p.setPen(Qt.PenStyle.NoPen)
            for _ in range(int(14 * glitch)):
                p.setBrush(random.choice([PINK, CYAN, WHITE, GREEN, PURPLE]))
                p.drawRect(random.randint(0, W - 20), random.randint(0, FIG_H),
                           random.randint(10, 90), random.randint(2, 8))

        # строки развёртки — вырезаем прозрачные полосы
        p.setCompositionMode(CM.CompositionMode_DestinationOut)
        p.drawImage(0, 0, self._scanlines)
        roll = (self.t * 5) % FIG_H
        p.setPen(QPen(QColor(0, 0, 0, 120), 6))
        p.drawLine(0, roll, W, roll)
        p.setCompositionMode(CM.CompositionMode_SourceOver)

        p.resetTransform()
        self._hud(p, glitch)
        p.end()

    def _tinted(self, image, color):
        if self.eye_pos is not None:
            return tinted(image, color)
        key = image.cacheKey(), color.rgba()
        if key not in self._tint_cache:
            self._tint_cache[key] = tinted(image, color)
            if len(self._tint_cache) > 12:
                self._tint_cache.popitem(last=False)
        self._tint_cache.move_to_end(key)
        return self._tint_cache[key]

    def _crt_line(self, p, width, height):
        x = (W - width) / 2
        y = FIG_H / 2 - height / 2
        p.fillRect(QRectF(x - 6, y - 3, width + 12, height + 6), QColor(255, 34, 96, 120))
        p.fillRect(QRectF(x, y, width, height), WHITE)

    def _hud(self, p, glitch):
        # на прогулке окно с текстом сверху, фигура под ним
        top = 6 if self.roaming else FIG_H + 6
        bottom = top + (H - FIG_H) - 12
        panel = QPolygonF([QPointF(6, top), QPointF(W - 22, top), QPointF(W - 6, top + 16),
                           QPointF(W - 6, bottom), QPointF(22, bottom), QPointF(6, bottom - 16)])
        p.setPen(QPen(PINK, 1.5))
        p.setBrush(QColor(10, 4, 16, 215))
        p.drawPolygon(panel)

        font = QFont("Consolas", 10)
        font.setBold(True)
        p.setFont(font)
        label = STATUS_TEXT.get(self.mode, "")
        if self.mode == "idle":
            label = {"hurt": "ОБИЖЕНА", "happy": "ДОВОЛЬНА", "playful": "ШАЛЮ", "bored": "СКУЧАЮ"}.get(self.mood, label)
        if self.sleeping:
            label = "ДРЕМЛЮ"
        status = "// CAPRI :: " + label
        p.setPen({"hurt": PURPLE, "happy": GREEN, "playful": PINK, "bored": CYAN}.get(self.mood, GREEN))
        p.drawText(16, top + 20, status)

        # «эквалайзер»
        level = {"speaking": 1.0, "listening": .5, "thinking": .3}.get(self.mode, .12)
        for i in range(10):
            h = 2 + random.random() * 14 * level
            p.fillRect(QRectF(W - 120 + i * 9, top + 22 - h, 6, h), PINK if i % 3 else CYAN)

        rect = QRectF(16, top + 30, W - 32, bottom - top - 34)
        font, text = self._prepare_subtitle(rect)
        p.setFont(font)
        p.setPen(QColor(0, 240, 255, 170))
        p.drawStaticText(rect.topLeft() + QPointF(1.5, 1), text)
        p.setPen(QColor(255, 200, 220))
        p.drawStaticText(rect.topLeft(), text)

    def _prepare_subtitle(self, rect):
        key = self.subtitle, rect.width(), rect.height(), DPR
        if key == self._subtitle_key:
            return self._subtitle_static
        # Текст ИИ может быть длинным: полный ответ остаётся в subtitle, ограничен только видимый фрагмент.
        full = self.subtitle[:4096]
        def layout(value, font):
            text = QStaticText(value)
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setTextWidth(rect.width())
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            text.setTextOption(option)
            text.prepare(QTransform(), font)
            return text
        for size in (10, 9, 8, 7):
            font = QFont("Consolas", size)
            text = layout(full, font)
            if text.size().height() <= rect.height():
                break
        if text.size().height() > rect.height() or len(self.subtitle) > len(full):
            lo, hi = 0, len(full)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if layout(full[:mid].rstrip() + "…", font).size().height() <= rect.height():
                    lo = mid
                else:
                    hi = mid - 1
            text = layout(full[:lo].rstrip() + "…", font)
        self._subtitle_key = key
        self._subtitle_static = font, text
        return self._subtitle_static

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(CM.CompositionMode_Source)
        p.drawImage(0, 0, self.frame)
        p.end()

    # ---------- мышь: клик — позвать, тащить — переместить, ПКМ — меню ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.wake_up()
            self.stop_roam()
            self._press_origin = e.globalPosition().toPoint()
            self._press = self._press_origin - self.pos()
            self._pat_x, self._pat_direction, self._pat_turns = None, 0, []
            self.hopping, self.hop_home, self.tele_target = False, None, None
            self.hide_at = 0
            self._moved = False
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(e.globalPosition().toPoint())

    def stroke_head(self, point, now):
        if (self._press is not None or self.state != "visible" or self.mode != "idle" or
                not W * .2 <= point.x() <= W * .8 or not 0 <= point.y() < FIG_H * .42):
            self._pat_x, self._pat_direction, self._pat_turns = None, 0, []
            return False
        if self._pat_x is None:
            self._pat_x = point.x()
            return False
        delta = point.x() - self._pat_x
        if abs(delta) < 10:
            return False
        self._pat_x = point.x()
        direction = 1 if delta > 0 else -1
        self._pat_turns = [stamp for stamp in self._pat_turns if now - stamp < 1.4]
        if self._pat_direction and direction != self._pat_direction:
            self._pat_turns.append(now)
        self._pat_direction = direction
        if len(self._pat_turns) >= 3 and now - self._last_pat >= 6:
            self._last_pat = now
            self._pat_turns.clear()
            self.wake_up()
            self.play_anim("desktop_grin")
            self.hide_at = now + self.hide_after
            self.petted.emit()
            return True
        return False

    def mouseMoveEvent(self, e):
        if self._press is None:
            self.stroke_head(e.position(), time.time())
            return
        cursor = e.globalPosition().toPoint()
        if not self._moved and (cursor - self._press_origin).manhattanLength() < 6:
            return
        if not self._moved:
            self._drag_started = time.time()
            self.anim = None
        self.move(cursor - self._press)
        self.hopping, self.hop_home, self.tele_target = False, None, None
        self._moved = True
        self.user_moved = True
        self.hide_at = 0

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._moved:
                self.hide_at = time.time() + self.hide_after if self.mode == "idle" else 0
                self.clicked.emit()
            else:
                screen = QGuiApplication.screenAt(e.globalPosition().toPoint()) or QGuiApplication.primaryScreen()
                rect = screen.availableGeometry()
                self.move(max(rect.left(), min(self.x(), rect.right() - W + 1)),
                          max(rect.top(), min(self.y(), rect.bottom() - H + 1)))
                self.hide_at = time.time() + self.hide_after if self.mode == "idle" else 0
                self.play_anim("desktop_grin")
            self._press = self._press_origin = None
