"""Validate and install a Colab phrase library without replacing local voice weights."""
import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

from capri.audio.voice_library import LIBRARY_ROOT, VoiceLibrary
from capri.config.settings import _edit_config


def install(archive, root=LIBRARY_ROOT, activate=True):
    archive, root = Path(archive), Path(root)
    root.mkdir(parents=True, exist_ok=True)
    identifier = hashlib.sha256(archive.read_bytes()).hexdigest()[:24]
    destination = root / identifier
    with tempfile.TemporaryDirectory(dir=root, prefix="import-") as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            if sum(item.file_size for item in source.infolist()) > 2 * 1024 ** 3:
                raise ValueError("Библиотека превышает 2 ГБ")
            for item in source.infolist():
                # Windows separators must be validated even when the installer is tested on Linux.
                if "\\" in item.filename or ":" in item.filename:
                    raise ValueError("Неверный путь в архиве")
                target = (temporary / item.filename).resolve()
                if not target.is_relative_to(temporary.resolve()):
                    raise ValueError("Путь за пределами библиотеки")
            source.extractall(temporary)
        library = VoiceLibrary(temporary)
        if not library.entries:
            raise ValueError("Библиотека пуста")
        if destination.exists():
            VoiceLibrary(destination)
        else:
            shutil.move(str(temporary), str(destination))
    if activate:
        error = _edit_config(lambda cfg: cfg.update(voice_library_path=str(destination)))
        if error:
            raise ValueError(error)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(install(args.archive))
