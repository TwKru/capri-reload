"""Пользовательский автозапуск Windows без административных прав."""
import os
import subprocess
import sys
from pathlib import Path

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def enabled():
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
            return bool(winreg.QueryValueEx(key,"Capri")[0])
    except OSError:
        return False


def set_enabled(value, base):
    if os.name != "nt":
        raise ValueError("Автозапуск через эту панель доступен в Windows.")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
        if value:
            executable = Path(sys.executable)
            if not getattr(sys,"frozen",False):
                silent = executable.with_name("pythonw.exe")
                executable = silent if silent.exists() else executable
                command = subprocess.list2cmdline([str(executable),str(Path(base)/"main.py")])
            else:
                command = subprocess.list2cmdline([str(executable)])
            winreg.SetValueEx(key,"Capri",0,winreg.REG_SZ,command)
        else:
            try:
                winreg.DeleteValue(key,"Capri")
            except FileNotFoundError:
                pass
