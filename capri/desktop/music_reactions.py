"""Танец от пиков выходного звука; микрофон не используется."""
import ctypes
import os
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication


class MusicLife(QObject):
    beat = Signal(float)
    playing = Signal(bool)

    def __init__(self, runtime):
        super().__init__(runtime)
        self.runtime = runtime
        self.stopped = threading.Event()
        self.beat.connect(self.on_beat)
        self.playing.connect(self.on_playing)
        self.auto = False
        if os.name == "nt" and QGuiApplication.platformName() != "offscreen":
            threading.Thread(target=self.work,daemon=True).start()

    def on_playing(self, playing):
        avatar = self.runtime.avatar
        enabled = self.runtime.capri.cfg.get("music_dance",False)
        if enabled and playing and avatar.mode == "idle" and not avatar.sleeping and not avatar.perched and avatar._press is None:
            if not self.auto and not avatar.anim:
                avatar.play_anim("desktop_dance")
                avatar.anim_loop = True
                avatar.hide_at = 0
                self.auto = True
        elif self.auto:
            if avatar.anim == "desktop_dance":
                avatar.anim = None
                avatar.anim_loop = False
            self.auto = False

    def on_beat(self, level):
        if self.auto:
            # Начало клипа синхронизируется с атакой звука.
            self.runtime.avatar.anim_start = time.time()

    def work(self):
        import comtypes
        comtypes.CoInitialize()
        meter, last, average, next_session, current = None, 0., .02, 0., False
        try:
            while not self.stopped.wait(.06):
                if not self.runtime.capri.cfg.get("music_dance",False):
                    self.playing.emit(False)
                    self.stopped.wait(1)
                    continue
                now = time.monotonic()
                try:
                    if now >= next_session:
                        from capri.platform.windows.media_controls import now_playing
                        info = now_playing()
                        current = bool(info and info[2])
                        self.playing.emit(current)
                        next_session = now+2
                    if meter is None:
                        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                        device = AudioUtilities.GetSpeakers()
                        meter = ctypes.cast(device._dev.Activate(IAudioMeterInformation._iid_,comtypes.CLSCTX_ALL,None),ctypes.POINTER(IAudioMeterInformation))
                    level = float(meter.GetPeakValue())
                    average = .94*average+.06*level
                    if current and level > max(.04,average*1.4) and now-last>.2:
                        last = now
                        self.beat.emit(level)
                except Exception:  # noqa: BLE001 -- ошибка внешнего интерфейса не останавливает приложение
                    meter = None
                    self.playing.emit(False)
                    self.stopped.wait(2)
        finally:
            comtypes.CoUninitialize()
