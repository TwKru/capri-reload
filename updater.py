"""Обновление Capri Reload из TwKru/capri-reload с сохранением личных файлов."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile

REPOSITORY = "TwKru/capri-reload"
BRANCH = "main"
PROJECT_URL = "https://github.com/" + REPOSITORY
VERSION_FILE = ".capri-version"
BACKUP_DIR = ".capri-update-backup"
PROTECTED_DIRS = {".git", ".ruff_cache", ".pytest_cache", "__pycache__", "models", "reports", "samples",
                  BACKUP_DIR, ".claude"}
PROTECTED_FILES = {"config.json", "capri.log", VERSION_FILE, "capri-update.log", ".capri-update.lock"}
log = logging.getLogger("capri.updater")


def latest_version():
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/{BRANCH}",
        headers={"User-Agent": "Capri-Reload-Updater", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        sha = json.load(response)["object"]["sha"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GitHub вернул неверную версию")
    return sha


def installed_version(base):
    try:
        sha = (Path(base) / VERSION_FILE).read_text(encoding="utf-8").strip()
        return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except FileNotFoundError:
        return None


def download(sha, destination):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Неверная версия")
    request = urllib.request.Request(f"https://codeload.github.com/{REPOSITORY}/zip/{sha}",
                                     headers={"User-Agent": "Capri-Reload-Updater"})
    size = 0
    with urllib.request.urlopen(request, timeout=30) as response, open(destination, "wb") as file:
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > 256 * 2**20:
                raise ValueError("Архив обновления слишком большой")
            file.write(chunk)


def protected(relative):
    return (any(part.lower() in PROTECTED_DIRS for part in relative.parts) or
            relative.name.lower() in PROTECTED_FILES or relative.suffix.lower() in (".pyc", ".log", ".tmp"))


def extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as zipped:
        total = 0
        roots = set()
        for entry in zipped.infolist():
            name = entry.orig_filename
            path = PurePosixPath(name)
            if "\\" in name or path.is_absolute() or any(part in ("..", ".") or ":" in part for part in path.parts):
                raise ValueError("Недопустимый путь в обновлении")
            if not path.parts:
                continue
            roots.add(path.parts[0])
            if len(roots) != 1:
                raise ValueError("Неизвестная структура архива")
            relative = Path(*path.parts[1:])
            if entry.is_dir() or not path.parts[1:] or protected(relative):
                continue
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Путь выходит за папку обновления")
            total += entry.file_size
            if total > 300 * 2**20 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Неподдерживаемое содержимое архива")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(entry) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
    if not (destination / "main.py").is_file():
        raise ValueError("В архиве нет main.py")
    for path in destination.rglob("*.py"):
        compile(path.read_bytes(), str(path), "exec")


def _same_file(first, second):
    if not second.is_file() or first.stat().st_size != second.stat().st_size:
        return False
    def digest(path):
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").digest()
    return digest(first) == digest(second)


def changed_files(staged, base):
    staged, base = Path(staged).resolve(), Path(base).resolve()
    changes = []
    for source in staged.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(staged)
        if protected(relative):
            continue
        destination = (base / relative).resolve()
        if not destination.is_relative_to(base):
            raise ValueError("Путь назначения выходит за папку Капри")
        if not _same_file(source, destination):
            changes.append(relative)
    return changes


def _atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as temp:
        staging = Path(temp.name)
    try:
        shutil.copy2(source, staging)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def install(staged, base, sha):
    base, staged = Path(base).resolve(), Path(staged).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not (base / "main.py").is_file():
        raise ValueError("Неверная версия или папка Капри")
    changes = changed_files(staged, base)
    backup = base / BACKUP_DIR / uuid.uuid4().hex
    if not backup.resolve().is_relative_to(base):
        raise ValueError("Папка резервной копии находится вне папки Капри")
    backup.mkdir(parents=True)
    applied = []
    try:
        for relative in changes + [Path(VERSION_FILE)]:
            destination = base / relative
            existed = destination.exists()
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            applied.append((relative, existed))
            if relative.name == VERSION_FILE:
                marker = backup / "new-version.txt"
                marker.write_text(sha + "\n", encoding="utf-8")
                _atomic_copy(marker, destination)
            else:
                _atomic_copy(staged / relative, destination)
    except Exception:
        for relative, existed in reversed(applied):
            if existed:
                shutil.copy2(backup / relative, base / relative)
            else:
                (base / relative).unlink(missing_ok=True)
        raise
    return len(changes), backup


def start_update(base, pid):
    return subprocess.Popen([sys.executable, str(Path(base) / "updater.py"), "--base", str(base),
                             "--pid", str(pid), "--restart"], cwd=base, creationflags=0x08000000)


def _stop_app(base, pid):
    import psutil
    for process in psutil.process_iter(["pid", "name"]):
        if process.pid == os.getpid() or (pid and process.pid != pid):
            continue
        if (process.info.get("name") or "").lower() not in ("python.exe", "pythonw.exe"):
            continue
        try:
            if Path(process.cwd()).resolve() != base:
                continue
            if not any(Path(arg).name.lower() == "main.py" for arg in process.cmdline()[1:]):
                continue
            process.terminate()
            process.wait(5)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            if pid:
                raise


def _restart(base):
    executable = Path(sys.executable).with_name("pythonw.exe")
    if not executable.exists():
        executable = Path(sys.executable)
    subprocess.Popen([str(executable), str(base / "main.py")], cwd=base, creationflags=0x08000000)


def _acquire_lock(base):
    import psutil
    path = base / ".capri-update.lock"
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(path.read_text().strip())
            except (ValueError, OSError):
                log.error("Не удалось прочитать блокировку обновления")
                return None
            if psutil.pid_exists(pid):
                log.info("Обновление уже запущено")
                return None
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w") as file:
            file.write(str(os.getpid()))
        return path
    return None


def main():
    parser = argparse.ArgumentParser(description="Обновление Capri Reload из GitHub")
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    base = args.base.resolve()
    if not (base / "main.py").is_file():
        raise SystemExit("В этой папке нет Капри")
    logging.basicConfig(filename=base / "capri-update.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = _acquire_lock(base)
    if lock is None:
        return 0
    stopped = False
    try:
        sha = latest_version()
        if sha == installed_version(base):
            log.info("Уже установлена последняя версия %s", sha)
            return 0
        with tempfile.TemporaryDirectory(prefix="capri_update_") as folder:
            archive, staged = Path(folder) / "update.zip", Path(folder) / "source"
            download(sha, archive)
            extract(archive, staged)
            changes = changed_files(staged, base)
            if Path("requirements.txt") in changes:
                result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(staged / "requirements.txt")],
                                        capture_output=True, timeout=300, creationflags=0x08000000)
                if result.returncode:
                    raise RuntimeError("Не удалось установить библиотеки. Запусти setup.bat")
            if args.restart and changes:
                _stop_app(base, args.pid)
                stopped = True
            count, backup = install(staged, base, sha)
            log.info("Обновлено до %s: %s файлов, резервная копия %s", sha, count, backup)
        if stopped:
            _restart(base)
        return 0
    except Exception as error:
        log.exception("Обновление не установлено")
        if stopped:
            _restart(base)
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"Обновление не установлено: {error}\n\nПодробности в capri-update.log.",
                                        "Capri Reload", 0x10)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
