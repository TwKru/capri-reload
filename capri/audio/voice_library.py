"""Exact-text recordings generated in Colab, stored separately from the disposable cache."""
import hashlib
import json
import os
import tempfile
import wave
from pathlib import Path

LIBRARY_ROOT = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Capri" / "voice-libraries"


def text_key(text):
    return " ".join(text.split())


class VoiceLibrary:
    def __init__(self, directory=None):
        self.root = Path(directory).resolve() if directory else None
        self.entries = {}
        self.revision = "disabled"
        if self.root is None:
            return
        raw = (self.root / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        if manifest.get("version") != 1 or manifest.get("processing") != "raw":
            raise ValueError("Нужна библиотека необработанных фраз версии 1")
        self.revision = hashlib.sha256(raw).hexdigest()
        for entry in manifest["entries"]:
            path = (self.root / entry["audio"]).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError("Файл библиотеки отсутствует или выходит за её папку")
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Повреждён файл библиотеки")
            with wave.open(str(path), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                    raise ValueError("Библиотека должна содержать моно PCM16 24 кГц")
                if not 0 < audio.getnframes() <= 24000 * 120:
                    raise ValueError("Недопустимая длительность фразы")
            self.entries[text_key(entry["text"])] = path

    def find(self, text):
        return self.entries.get(text_key(text))
