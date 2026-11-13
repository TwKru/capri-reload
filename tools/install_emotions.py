"""Prepare voicenew/emotions/{giggle,laugh,exclaim,sigh,gasp} for local playback."""
import os
import tempfile
from pathlib import Path

from capri.audio.voice_service import decode, write_wav
from capri.config.settings import _edit_config
from tools.voice_lab import AUDIO_EXTENSIONS


def install(source=Path("voicenew/emotions"), destination=None):
    import numpy as np
    destination = Path(destination or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) /
                       "Capri" / "emotions")
    count = 0
    for event in ("giggle", "laugh", "exclaim", "sigh", "gasp", "huff"):
        for path in sorted((Path(source) / event).glob("*")):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            audio = decode(str(path))
            if not .1 * 24000 <= len(audio) <= 6 * 24000 or not np.isfinite(audio).all():
                raise ValueError(f"Эмоция должна длиться 0,1–6 секунд: {path}")
            if float(np.max(np.abs(audio))) < .001:
                raise ValueError(f"Пустая запись: {path}")
            import hashlib
            identifier = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
            target = destination / event
            target.mkdir(parents=True, exist_ok=True)
            write_wav(str(target / f"{identifier}.wav"), audio)
            count += 1
    if count:
        error = _edit_config(lambda cfg: cfg.update(voice_emotions_path=str(destination)))
        if error:
            raise ValueError(error)
    print(f"Записей эмоций: {count}")
    return count


if __name__ == "__main__":
    install()
