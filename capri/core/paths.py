"""Пути приложения не зависят от cwd и глубины Python-пакетов."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PROJECT_ROOT
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))

# Имена пользовательских файлов — часть формата данных, их нельзя менять при рефакторинге.
PRIVATE_FILENAMES = frozenset({
    "config.json", "memory.json", "me.md", "personality.md", "personality.backup.md",
    "jobs.sqlite", "jobs.sqlite-wal", "jobs.sqlite-shm", "jobs.sqlite-journal",
    "capri.log", "capri-crash.log", "capri-update.log",
})
