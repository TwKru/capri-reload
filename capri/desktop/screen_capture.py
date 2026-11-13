"""Снимки только в памяти: для явного запроса и включённого пользователем наблюдения."""
import base64
import threading
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage

from capri.core import cancellation


def encode_frame(image, rect, max_side=960):
    image = image.scaled(max_side,max_side,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
    pixels = image.scaled(16,16).convertToFormat(QImage.Format.Format_Grayscale8)
    digest = bytes(pixels.constBits())
    data=QByteArray()
    buffer=QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer,"JPEG",65)
    return {"image":base64.b64encode(bytes(data)).decode("ascii"),"width":image.width(),"height":image.height(),
            "rect":list(rect),"fingerprint":list(digest)}


class ScreenFrames(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._capture)

    def _capture(self, state):
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                raise ValueError("Экран недоступен")
            image = screen.grabWindow(0).toImage()
            if image.isNull():
                raise ValueError("Нет доступа к снимку экрана. Проверь разрешения системы.")
            rect = screen.geometry()
            state["frame"] = encode_frame(image,(rect.x(),rect.y(),rect.width(),rect.height()),state.get("max_side",960))
        except Exception as error:  # noqa: BLE001 -- граница фонового задания: ошибка передаётся в интерфейс
            state["error"] = str(error)
        finally:
            state["ready"].set()

    def get(self, max_side=960):
        from PySide6.QtCore import QThread
        state={"ready":threading.Event(), "max_side":max_side}
        if QThread.currentThread() == self.thread():
            self._capture(state)
        else:
            self.requested.emit(state)
        if not cancellation.wait_event(state["ready"],5):
            raise ValueError("Снимок экрана не получен")
        if "error" in state:
            raise ValueError(state["error"])
        return state["frame"]


class WatchGate:
    def __init__(self):
        self.next_at = 0
        self.last = None
        self.last_line = ""

    def due(self, enabled, busy, interval=300, now=None):
        now = time.monotonic() if now is None else now
        if not enabled or busy or now < self.next_at:
            return False
        self.next_at = now + max(60,float(interval))
        return True

    def changed(self, frame):
        value=frame["fingerprint"]
        changed = self.last is None or len(value)!=len(self.last) or sum(abs(a-b) for a,b in zip(value,self.last))/len(value)>5
        self.last=value
        return changed
