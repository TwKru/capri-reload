"""Выбор разговорной модели по запущенным играм, без глобального игрового режима."""
import ctypes
from ctypes import wintypes
import logging
import os
import time

import psutil

log = logging.getLogger("capri")
BROWSERS_AND_TOOLS = {"chrome.exe", "msedge.exe", "firefox.exe", "browser.exe", "opera.exe",
                      "explorer.exe", "python.exe", "pythonw.exe", "steam.exe", "steamwebhelper.exe",
                      "epicgameslauncher.exe", "vlc.exe", "mpv.exe", "applicationframehost.exe",
                      "nvidia overlay.exe", "gamebar.exe"}
KNOWN_GAMES = {"rustclient.exe", "rust.exe", "cs2.exe", "dota2.exe", "gta5.exe", "gta5_enhanced.exe",
               "fortniteclient-win64-shipping.exe", "cyberpunk2077.exe", "witcher3.exe"}
GAME_HELPERS = {"crashpad_handler.exe", "unitycrashhandler64.exe", "unitycrashhandler32.exe",
                "crashreportclient.exe", "easyanticheat.exe", "easyanticheat_eos.exe",
                "battleye.exe", "beservice.exe"}


def game_executable(name, executable, additional=()):
    name = name.lower()
    if not name or name in BROWSERS_AND_TOOLS or name in GAME_HELPERS:
        return False
    path = executable.replace("\\", "/").lower()
    return name in KNOWN_GAMES or name in additional or any(part in path for part in
            ("/steamapps/common/", "/epic games/", "/.minecraft/"))


def game_window(name, executable, window, monitor, style, additional=()):
    name = name.lower()
    if name in BROWSERS_AND_TOOLS:
        return False
    if game_executable(name, executable, additional):
        return True
    if style & 0x00C00000 == 0x00C00000:
        return False
    left, top, right, bottom = window
    ml, mt, mr, mb = monitor
    return left <= ml + 2 and top <= mt + 2 and right >= mr - 2 and bottom >= mb - 2


def foreground_game(additional=()):
    """Один снимок при запросе, без таймера и без чтения памяти игры."""
    try:
        user = ctypes.windll.user32
        user.GetForegroundWindow.restype = wintypes.HWND
        user.IsIconic.argtypes = (wintypes.HWND,)
        user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        hwnd = user.GetForegroundWindow()
        if not hwnd or user.IsIconic(hwnd):
            return False
        kind = ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd, kind, len(kind))
        if kind.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = psutil.Process(pid.value)
        name = process.name()
        try:
            executable = process.exe()
        except (psutil.AccessDenied, OSError):
            executable = ""
        user.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        user.MonitorFromWindow.restype = wintypes.HANDLE
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        user.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        rect = wintypes.RECT()
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)) or not user.GetMonitorInfoW(
                user.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
            return name.lower() in KNOWN_GAMES or name.lower() in additional
        coords = lambda r: (r.left, r.top, r.right, r.bottom)
        return game_window(name, executable, coords(rect), coords(info.rcMonitor), user.GetWindowLongW(hwnd, -16), additional)
    except (OSError, AttributeError, psutil.Error):
        return False


def game_running(additional=()):
    """Проверка при запросе: свёрнутая игра тоже требует лёгкой модели."""
    try:
        for process in psutil.process_iter(["name", "exe"], ad_value=""):
            if game_executable(process.info.get("name") or "", process.info.get("exe") or "", additional):
                return True
    except (OSError, psutil.Error):
        pass
    return foreground_game(additional)


class ConversationModels:
    def __init__(self, cfg):
        self.enabled = bool(cfg.get("use_light_model_in_games", True))
        self.light = cfg.get("game_chat_model", "qwen3:1.7b")
        additional = cfg.get("game_executables", [])
        self.additional = {os.path.basename(name).lower() for name in additional if isinstance(name, str)} if isinstance(additional, list) else set()
        self.names = None
        self.checked = 0.0
        self.last = None

    def choose(self, normal, installed):
        if not self.enabled or not game_running(self.additional):
            return normal
        if self.names is None or time.monotonic() - self.checked > 30:
            self.names = installed() or []
            self.checked = time.monotonic()
        if self.light not in self.names:
            log.info("Лёгкая разговорная модель %s не установлена, использую %s", self.light, normal)
            return normal
        return self.light

    def prepare(self, selected, normal, release):
        """Вызывается под блокировкой ИИ, только при смене модели для реального запроса."""
        if selected == self.last:
            return
        other = normal if selected == self.light else self.light
        if other != selected:
            try:
                release(other)
            except (OSError, ValueError):
                log.info("Не удалось освободить предыдущую разговорную модель %s", other)
        self.last = selected
        log.info("Разговорная модель: %s", selected)
