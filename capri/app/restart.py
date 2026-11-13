"""Start a replacement only after the current application's process has exited."""
import os
import subprocess
import sys
from pathlib import Path

import psutil

from capri.core.paths import APP_ROOT

WAIT_FLAG = "--wait-for-pid"


def restart_command(base=APP_ROOT, executable=None, frozen=None, pid=None):
    executable = Path(executable or sys.executable)
    frozen = getattr(sys,"frozen",False) if frozen is None else frozen
    if frozen:
        command = [str(executable)]
    else:
        windowless = executable.with_name("pythonw.exe")
        if os.name == "nt" and windowless.is_file():
            executable = windowless
        command = [str(executable),str(Path(base)/"main.py")]
    return command+[WAIT_FLAG,str(os.getpid() if pid is None else pid)]


def spawn_replacement(base=APP_ROOT):
    return subprocess.Popen(restart_command(base),cwd=base,
        creationflags=0x08000000 if os.name == "nt" else 0)


def wait_for_previous(pid, timeout=30):
    pid = int(pid)
    if pid <= 0 or pid == os.getpid():
        raise ValueError("Неверный процесс для перезапуска Капри")
    try:
        psutil.Process(pid).wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        return False  # Не создаём второй интерфейс, пока старая копия ещё жива.
    return True
