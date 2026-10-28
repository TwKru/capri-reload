"""Ставит офлайн-модель распознавания речи Vosk в папку models/.

    python tools/download_model.py

Вызывается из setup.bat. Модель лежит в самом архиве Капри (bundled/), поэтому интернет и VPN не нужны.
Если архива модели нет — скачивает её с сайта разработчиков. Повторный запуск ничего не делает,
если модель уже на месте."""
import os
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "vosk-model-small-ru-0.22"
URL = f"https://alphacephei.com/vosk/models/{NAME}.zip"
BUNDLED = os.path.join(BASE, "bundled", NAME + ".zip")  # копия модели в репозитории (лицензия Apache 2.0)
MODELS = os.path.join(BASE, "models")
TARGET = os.path.join(MODELS, NAME)
MODEL_SHA256 = "5525af7834b816319e20996416579b1adf448bf29fba7025cb8014c940468606"


def ready():
    return os.path.isfile(os.path.join(TARGET, "am", "final.mdl"))


def download(path):
    with urllib.request.urlopen(URL, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if done > 128 * 2**20:
                raise ValueError("Архив модели слишком большой")
            if total:
                print(f"\r  {done / 2**20:.0f} / {total / 2**20:.0f} МБ", end="", flush=True)
    print()
    if total and done < total:
        raise IOError("загрузка оборвалась")


def unpack(archive):
    with open(archive, "rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("Контрольная сумма модели не совпала")
    models = Path(MODELS).resolve()
    target = Path(TARGET)
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)() or target.resolve() != models / NAME:
        raise ValueError("Небезопасный путь модели")
    models.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=models, prefix=".unpack-") as folder:
        staged = Path(folder)
        with zipfile.ZipFile(archive) as zipped:
            total, seen = 0, set()
            for entry in zipped.infolist():
                path = PurePosixPath(entry.orig_filename)
                if (not path.parts or path.parts[0] != NAME or "\\" in entry.orig_filename or
                        path.is_absolute() or any(part in (".", "..") or ":" in part or
                        part.endswith((".", " ")) or any(ord(c) < 32 for c in part) or
                        re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", part, re.I)
                        for part in path.parts) or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Недопустимый путь в архиве модели")
                key = "/".join(path.parts).casefold()
                if key in seen:
                    raise ValueError("Повторяющийся путь в архиве модели")
                seen.add(key)
                total += entry.file_size
                if total > 256 * 2**20:
                    raise ValueError("Распакованная модель слишком большая")
                if entry.is_dir():
                    continue
                output = staged.joinpath(*path.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, output.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        if not (staged / NAME / "am" / "final.mdl").is_file():
            raise ValueError("В архиве нет модели распознавания")
        previous = staged / "previous"
        existed = target.exists()
        if existed:
            target.rename(previous)
        try:
            (staged / NAME).rename(target)
        except Exception:
            if existed:
                previous.rename(target)
            raise


def main():
    if ready():
        print("[Capri] Модель распознавания речи уже установлена.")
        return 0
    os.makedirs(MODELS, exist_ok=True)
    if os.path.isfile(BUNDLED):
        print("[Capri] Распаковываю модель распознавания речи...")
        try:
            unpack(BUNDLED)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            print(f"  не получилось ({e}), попробую скачать")
    if not ready():
        tmp = os.path.join(MODELS, "ru.zip")
        print("[Capri] Скачиваю модель распознавания речи (~45 МБ)...")
        for attempt in range(3):
            try:
                download(tmp)
                break
            except Exception as e:
                print(f"  не получилось ({e}), попытка {attempt + 2} из 3..." if attempt < 2 else f"  ошибка: {e}")
        else:
            print("[Capri] Не удалось скачать модель. Скачай Капри с GitHub заново (модель лежит в архиве,")
            print("        в папке bundled) или включи VPN и запусти setup.bat ещё раз.")
            return 1
        unpack(tmp)
        os.remove(tmp)
    if not ready():
        print("[Capri] Архив распаковался, но модели в нём нет. Скачай Капри с GitHub заново.")
        return 1
    print("[Capri] Модель установлена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
