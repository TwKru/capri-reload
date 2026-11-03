"""Окна и значки как опоры, переноска на курсоре, масштаб и глобальные клавиши."""
import ctypes
import logging
import os
import random
import shutil
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QGuiApplication

log = logging.getLogger("capri.desktop")


@dataclass(frozen=True)
class Surface:
    key: str
    title: str
    left: int
    top: int
    right: int
    bottom: int
    kind: str = "window"


def window_surfaces(exclude=()):
    if os.name != "nt":
        if shutil.which("wmctrl"):
            result = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True, timeout=3, check=False)
            rows = []
            for line in result.stdout.splitlines():
                parts = line.split(None, 7)
                try:
                    ident, _, x, y, w, h = parts[:6]
                    rows.append(Surface(ident, parts[-1], int(x), int(y), int(x)+int(w), int(y)+int(h)))
                except (ValueError, IndexError):
                    continue
            return rows
        return []
    user = ctypes.windll.user32
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    rows = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, parameter):
        if int(hwnd) in exclude or not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):
            return True
        rect, title = wintypes.RECT(), ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, 512)
        if title.value and user.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right-rect.left>100 and rect.bottom-rect.top>60:
            rows.append(Surface(str(int(hwnd)), title.value, rect.left, rect.top, rect.right, rect.bottom))
        return True
    user.EnumWindows(visit, 0)
    return rows


def icon_surfaces():
    """UI Automation читает положение значков Explorer без записи в чужой процесс."""
    if os.name != "nt":
        return []
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    try:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as ui
        automation = comtypes.client.CreateObject(ui.CUIAutomation, interface=ui.IUIAutomation)
        user = ctypes.windll.user32
        user.FindWindowExW.argtypes = [wintypes.HWND,wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR]
        user.FindWindowExW.restype = wintypes.HWND
        views = []
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,parameter):
            definition = user.FindWindowExW(hwnd,None,"SHELLDLL_DefView",None)
            if definition:
                view = user.FindWindowExW(definition,None,"SysListView32",None)
                if view:
                    views.append(view)
            return True
        user.EnumWindows(visit,0)
        rows = []
        for handle in views:
            view = automation.ElementFromHandle(handle)
            items = view.FindAll(2, automation.CreatePropertyCondition(30003, 50007))
            for number in range(items.Length):
                item = items.GetElement(number)
                rect = item.CurrentBoundingRectangle
                if rect.right > rect.left and rect.bottom > rect.top:
                    rows.append(Surface("icon:"+item.CurrentName, item.CurrentName, rect.left, rect.top,
                                        rect.right, rect.bottom, "icon"))
        return rows
    finally:
        comtypes.CoUninitialize()


def nearest_surface(surfaces, x, feet_y, tolerance=110):
    choices = [row for row in surfaces if row.left-30 <= x <= row.right+30 and abs(row.top-feet_y) <= tolerance]
    return min(choices, key=lambda row: abs(row.top-feet_y)) if choices else None


def current_window_surface(surface):
    """Track the attached window between the slower background inventory scans."""
    if surface.kind != "window" or os.name != "nt" or QGuiApplication.platformName() == "offscreen":
        return surface
    user = ctypes.windll.user32
    handle = wintypes.HWND(int(surface.key))
    rect = wintypes.RECT()
    if not user.IsWindowVisible(handle) or user.IsIconic(handle) or not user.GetWindowRect(handle,ctypes.byref(rect)):
        return None
    row = Surface(surface.key,surface.title,rect.left,rect.top,rect.right,rect.bottom)
    return logical_surfaces([row])[0]


def logical_surfaces(rows):
    """UIA/Win32 используют физические координаты, Qt — логические по мониторам."""
    screens = {screen.name().upper():screen for screen in QGuiApplication.screens()}
    monitors = []
    class Info(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("rect",wintypes.RECT),("work",wintypes.RECT),
                    ("flags",wintypes.DWORD),("device",wintypes.WCHAR*32)]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMONITOR,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    def visit(monitor,dc,rect,parameter):
        info = Info(); info.size = ctypes.sizeof(info)
        user = ctypes.windll.user32
        user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,ctypes.POINTER(Info)]
        if user.GetMonitorInfoW(monitor,ctypes.byref(info)):
            screen = screens.get(info.device.upper())
            if screen:
                geometry = screen.geometry()
                physical = info.rect
                monitors.append((physical.left,physical.top,physical.right,physical.bottom,geometry))
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None,None,visit,0)
    converted = []
    for row in rows:
        monitor = next((m for m in monitors if m[0] <= (row.left+row.right)/2 < m[2] and m[1] <= row.top < m[3]),None)
        if monitor:
            left,top,right,bottom,geo = monitor
            sx,sy = geo.width()/max(1,right-left),geo.height()/max(1,bottom-top)
            converted.append(Surface(row.key,row.title,round(geo.x()+(row.left-left)*sx),round(geo.y()+(row.top-top)*sy),
                round(geo.x()+(row.right-left)*sx),round(geo.y()+(row.bottom-top)*sy),row.kind))
        else:
            converted.append(row)
    return converted


class DesktopLife(QObject):
    discovered = Signal(object)

    def __init__(self, avatar):
        super().__init__(avatar)
        self.avatar = avatar
        self.surfaces = []
        self.attached = None
        self.offset = 0.5
        self.cursor = False
        self.hanging = False
        self.busy = False
        self.last_scan = 0
        self.window_scan = 0
        self.enabled = True
        self.icon_cache = []
        self.wander, self.next_window = False, time.monotonic()+45
        self.discovered.connect(self._accept)
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        avatar.desktop_life = self

    def _accept(self, surfaces):
        if os.name == "nt" and QGuiApplication.platformName() != "offscreen":
            surfaces = logical_surfaces(surfaces)
        self.surfaces, self.busy = surfaces, False

    def scan(self):
        if self.busy or QGuiApplication.platformName() == "offscreen":
            return
        self.busy = True
        own = int(self.avatar.winId())
        def work():
            try:
                rows = window_surfaces((own,))
                if time.monotonic()-self.last_scan > 8:
                    try:
                        self.icon_cache = icon_surfaces()
                        rows += self.icon_cache
                    except Exception:
                        log.debug("Значки рабочего стола недоступны",exc_info=True)
                    self.last_scan = time.monotonic()
                else:
                    rows += self.icon_cache
                self.discovered.emit(rows)
            except Exception:
                log.debug("Не удалось получить опоры",exc_info=True)
                self.discovered.emit([])
        threading.Thread(target=work, daemon=True).start()

    def detach(self):
        self.attached, self.cursor, self.hanging = None, False, False
        self.avatar.perched = False
        self.avatar.hanging = False
        self.timer.setInterval(120)

    def ride_cursor(self):
        self.detach()
        self.cursor = True
        self.avatar.summon()
        self.avatar.stop_motion()
        self.avatar.hide_at = 0
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.tick()

    def drop(self, modifiers=Qt.KeyboardModifier.NoModifier):
        self.detach()
        avatar = self.avatar
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.hanging = avatar.hanging = True
            avatar.hide_at = 0
            return
        if not self.enabled:
            return
        anchor = avatar.seat_anchor()
        feet = avatar.y() + anchor.y()
        surface = nearest_surface(self.surfaces, avatar.x()+anchor.x(), feet)
        if surface:
            self.attached = surface
            self.offset = min(1., max(0., (avatar.x()+anchor.x()-surface.left)/max(1,surface.right-surface.left)))
            avatar.stop_motion()
            avatar.perched = True
            avatar.move(avatar.x(), round(surface.top-anchor.y()))
            avatar.hide_at = 0
            self.timer.setInterval(33)
            avatar.render()
            avatar.update()

    def hop_window(self):
        candidates = [row for row in self.surfaces if row.kind == "window" and row.top > 100]
        if not candidates:
            self.scan()
            return
        current = next((i for i, row in enumerate(candidates) if self.attached and row.key == self.attached.key), -1)
        target = candidates[(current+1) % len(candidates)]
        self.attached, self.offset = target, .5
        self.cursor = False
        self.avatar.summon()
        self.avatar.stop_motion()
        self.avatar.perched = True
        self.avatar.hide_at = 0
        self.timer.setInterval(33)
        self.tick()

    def tick(self):
        avatar = self.avatar
        if not self.busy and time.monotonic()-self.window_scan > .5:
            self.window_scan = time.monotonic()
            self.scan()
        if not avatar.isVisible() or avatar._press is not None:
            return
        if self.wander and not self.cursor and not avatar.sleeping and avatar.mode == "idle" and time.monotonic()>=self.next_window:
            self.next_window = time.monotonic()+random.uniform(35,75)
            self.hop_window()
        if self.cursor:
            point = QCursor.pos() + QPoint(18, 18)
            screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            avatar.move(max(area.left(), min(point.x(), area.right()-avatar.width()+1)),
                        max(area.top(), min(point.y(), area.bottom()-avatar.height()+1)))
            avatar.hide_at = 0
        elif self.attached:
            updated = next((row for row in self.surfaces if row.key == self.attached.key), None)
            if updated is not None:
                updated = current_window_surface(updated)
            if updated is None:
                self.detach()
                return
            self.attached = updated
            anchor = avatar.seat_anchor()
            x = updated.left + (updated.right-updated.left)*self.offset-anchor.x()
            avatar.move(round(x), round(updated.top-anchor.y()))
            avatar.hide_at = 0


HOTKEYS = {"talk": "Ctrl+Alt+V", "mute": "Ctrl+Alt+N", "type": "Ctrl+Alt+T", "hide": "Ctrl+Alt+H", "detach": "Ctrl+Alt+C"}


class GlobalHotkeys(QAbstractNativeEventFilter):
    """RegisterHotKey вместо перехвата всего клавиатурного потока."""
    def __init__(self, callbacks, sequences=None):
        super().__init__()
        self.callbacks, self.ids, self.errors = callbacks, {}, []
        self.configure(sequences or HOTKEYS)

    @staticmethod
    def parse(sequence):
        parts = sequence.upper().split("+")
        if not all(part in ("ALT","CTRL","SHIFT","WIN") for part in parts[:-1]):
            raise ValueError("Неизвестный модификатор сочетания")
        modifiers = sum(value for key, value in (("ALT",1),("CTRL",2),("SHIFT",4),("WIN",8)) if key in parts[:-1])
        name = parts[-1]
        key = ord(name) if len(name)==1 and name.isascii() and name.isalnum() else {"ESC":27,"ESCAPE":27,"SPACE":32,"ENTER":13,"TAB":9,"HOME":36,"END":35,"LEFT":37,"UP":38,"RIGHT":39,"DOWN":40}.get(name)
        if name.startswith("F") and name[1:].isdigit() and 1<=int(name[1:])<=24:
            key = 111+int(name[1:])
        if key is None or (not modifiers and key != 27):
            raise ValueError("Нужна комбинация Ctrl/Alt/Shift/Win и буквы")
        return modifiers | 0x4000, key

    def configure(self, sequences):
        self.close()
        if os.name != "nt" or QGuiApplication.platformName() == "offscreen":
            self.errors = ["Глобальные клавиши доступны в Windows; на этой платформе используй меню."]
            return
        for number, (name, sequence) in enumerate(sequences.items(), 701):
            try:
                modifiers, key = self.parse(sequence)
                if not ctypes.windll.user32.RegisterHotKey(None, number, modifiers, key):
                    raise ValueError("Комбинация занята: " + sequence)
                self.ids[number] = name
            except ValueError as error:
                self.errors.append(str(error))

    def set_job_active(self, active):
        if os.name == "nt" and QGuiApplication.platformName() != "offscreen":
            ctypes.windll.user32.UnregisterHotKey(None, 799)
            self.ids.pop(799, None)
            if active and ctypes.windll.user32.RegisterHotKey(None, 799, 0x4000, 27):
                self.ids[799] = "stop"

    def nativeEventFilter(self, event_type, message):
        if os.name == "nt":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.ids:
                callback = self.callbacks.get(self.ids[msg.wParam])
                if callback:
                    callback()
                return True, 0
        return False, 0

    def close(self):
        if os.name == "nt":
            for number in self.ids:
                ctypes.windll.user32.UnregisterHotKey(None, number)
        self.ids, self.errors = {}, []
