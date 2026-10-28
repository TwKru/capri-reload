"""Определение полноэкранного приложения без хуков, опроса игр и захвата экрана."""
import ctypes
from ctypes import wintypes


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def covers_monitor(window, monitor, tolerance=2):
    left, top, right, bottom = window
    ml, mt, mr, mb = monitor
    return (left <= ml + tolerance and top <= mt + tolerance and
            right >= mr - tolerance and bottom >= mb - tolerance)


def fullscreen_app_active():
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.IsIconic.argtypes = (wintypes.HWND,)
        user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        window = user32.GetForegroundWindow()
        if not window or user32.IsIconic(window):
            return False
        name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(window, name, len(name))
        if name.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        monitor = user32.MonitorFromWindow(window, 2)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
        rect = wintypes.RECT()
        if not user32.GetWindowRect(window, ctypes.byref(rect)) or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        def bounds(r):
            return r.left, r.top, r.right, r.bottom
        return covers_monitor(bounds(rect), bounds(info.rcMonitor))
    except (OSError, AttributeError):
        return False
