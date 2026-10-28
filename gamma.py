"""Гамма основного монитора Windows с сохранением исходной калибровки."""
import ctypes
import json
import math
import os
import tempfile
import threading
from ctypes import wintypes

MAX_GAMMA = 4.5
MIN_GAMMA = 0.5
Ramp = ctypes.c_ushort * (3 * 256)
_lock = threading.Lock()


def make_ramp(gamma):
    if gamma <= 0:
        raise ValueError("Гамма должна быть положительной")
    # Windows ограничивает отклонение от линейной таблицы. Чёрный и белый сохраняем.
    channel = [min(65535, i * 257 + 32767, round((i / 255) ** (1 / gamma) * 65535))
               for i in range(256)]
    return channel * 3


def _backup_path():
    return os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Capri", "gamma_backup.json")


def _load_backup():
    try:
        with open(_backup_path(), encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or any(
            not isinstance(values, list) or len(values) != 768 or
            any(type(value) is not int or not 0 <= value <= 65535 for value in values)
            for values in data.values()):
        raise ValueError("Повреждена сохранённая исходная гамма")
    return data


def _save_backup(data):
    path = _backup_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                     suffix=".tmp", delete=False) as file:
        staging = file.name
        try:
            json.dump(data, file)
        except Exception:
            file.close()
            os.remove(staging)
            raise
    try:
        os.replace(staging, path)
    finally:
        if os.path.exists(staging):
            os.remove(staging)


class _DisplayDevice(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


class _GammaDevice:
    def __enter__(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        enum = user.EnumDisplayDevicesW
        enum.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DisplayDevice), wintypes.DWORD]
        enum.restype = wintypes.BOOL
        index = 0
        while True:
            display = _DisplayDevice()
            display.cb = ctypes.sizeof(display)
            if not enum(None, index, ctypes.byref(display), 0):
                raise OSError("Основной монитор не найден")
            if display.StateFlags & 1 and display.StateFlags & 4:
                self.name = display.DeviceName
                break
            index += 1
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        self.gdi.CreateDCW.restype = wintypes.HDC
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi.DeleteDC.restype = wintypes.BOOL
        for function in (self.gdi.GetDeviceGammaRamp, self.gdi.SetDeviceGammaRamp):
            function.argtypes = [wintypes.HDC, ctypes.c_void_p]
            function.restype = wintypes.BOOL
        self.hdc = self.gdi.CreateDCW("DISPLAY", self.name, None, None)
        if not self.hdc:
            raise OSError("Не удалось открыть настройки монитора")
        return self

    def __exit__(self, *args):
        self.gdi.DeleteDC(self.hdc)

    def read(self):
        ramp = Ramp()
        if not self.gdi.GetDeviceGammaRamp(self.hdc, ctypes.byref(ramp)):
            raise OSError("Драйвер не позволяет прочитать гамму")
        return list(ramp)

    def write(self, values):
        ramp = Ramp(*values)
        if not self.gdi.SetDeviceGammaRamp(self.hdc, ctypes.byref(ramp)):
            raise OSError("Драйвер не позволяет изменить гамму")

    def write_checked(self, values):
        self.write(values)
        # SetDeviceGammaRamp иногда сообщает успех, ничего не изменив. Допускаем округление DAC.
        if any(abs(actual - expected) > 257 for actual, expected in zip(self.read(), values)):
            raise OSError("Драйвер не применил гамму. Проверь HDR или настройки видеокарты")


def _apply(device, values):
    previous = device.read()
    try:
        device.write_checked(values)
    except Exception:
        device.write(previous)
        raise


def set_gamma(value):
    value = float(value)
    if not math.isfinite(value) or not MIN_GAMMA <= value <= MAX_GAMMA:
        raise ValueError(f"Укажи гамму от {MIN_GAMMA:g} до {MAX_GAMMA:g}")
    with _lock, _GammaDevice() as device:
        backup = _load_backup()
        if device.name not in backup:
            backup[device.name] = device.read()
            _save_backup(backup)  # сохраняем до изменения, в том числе для возврата после перезапуска
        _apply(device, make_ramp(value))


def night():
    set_gamma(MAX_GAMMA)


def restore():
    with _lock, _GammaDevice() as device:
        backup = _load_backup()
        if device.name not in backup:
            return False
        _apply(device, backup[device.name])
        del backup[device.name]
        _save_backup(backup)
        return True
