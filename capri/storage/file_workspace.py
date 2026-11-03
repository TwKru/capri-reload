"""Чтение и правка только выбранных пользователем текстовых файлов."""
import hashlib
import os
import tempfile
from pathlib import Path

MAX_BYTES = 1_048_576


class FileWorkspace:
    def __init__(self, paths=()):
        self.grants = {str(Path(path).absolute()): str(Path(path).resolve()) for path in paths}
        self.observed = {}

    def resolve(self, name):
        matches = [Path(path) for path, resolved in self.grants.items() if name in (path, Path(path).name)]
        if len(matches) != 1:
            raise ValueError("Выбери этот файл в разделе «Файлы»; имя должно быть однозначным.")
        path = matches[0]
        if str(path.resolve()) != self.grants[str(path)]:
            raise ValueError("Ссылка на файл изменилась. Выбери файл заново.")
        return path

    def read(self, name):
        path = self.resolve(name)
        if path.exists():
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES+1)
        else:
            data = b""
        if len(data) > MAX_BYTES or b"\0" in data:
            raise ValueError("Поддерживаются текстовые файлы до 1 МБ.")
        text = data.decode("utf-8-sig")
        self.observed[str(path)] = hashlib.sha256(data).hexdigest()
        return text

    def write(self, name, text):
        path = self.resolve(name)
        current = path.read_bytes() if path.exists() else b""
        baseline = self.observed.get(str(path))
        if baseline is None:
            raise ValueError("Перед записью прочитай выбранный файл.")
        if hashlib.sha256(current).hexdigest() != baseline:
            raise ValueError("Файл изменился после чтения. Прочитай его заново перед записью.")
        data = text.encode("utf-8")
        if len(data) > MAX_BYTES:
            raise ValueError("Запись больше 1 МБ.")
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".capri-edit-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                path.with_name(path.name+".capri-backup").write_bytes(current)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.observed[str(path)] = hashlib.sha256(data).hexdigest()

    def replace(self, name, old, new):
        text = self.read(name)
        if not old or text.count(old) != 1:
            raise ValueError("Заменяемый фрагмент должен встречаться ровно один раз.")
        self.write(name, text.replace(old, new, 1))

    def restore(self, name):
        path = self.resolve(name)
        backup = path.with_name(path.name+".capri-backup")
        text = backup.read_text(encoding="utf-8-sig")
        self.read(name)
        self.write(name, text)
