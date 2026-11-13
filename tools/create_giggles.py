"""Create reusable synthetic giggles in the current fast voice and install the bank."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from capri.audio.voice_service import Speaker, _ffmpeg, decode, micro_double, pitch_shift, write_wav
from capri.config.settings import CONFIG_PATH, _edit_config
from capri.core.paths import PROJECT_ROOT


def create():
    cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8-sig"))
    root = Path(cfg.get("voice_emotions_path") or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) /
                "Capri" / "emotions")
    bank = root / "giggle"
    bank.mkdir(parents=True, exist_ok=True)
    raw_cfg = dict(cfg, tts_engine="silero", voice_fx=0, voice_shift=0, voice_glitch=0,
                   voice_lively=True, voice_volume=100, voice_library_path="")
    speaker = Speaker(raw_cfg)
    pieces = []
    for index, text in enumerate(("Хи-хи!", "Хе-хе!", "Хи-хи-хи!"), 1):
        path = bank / f"generated_silero_{index}.wav"
        with tempfile.TemporaryDirectory(prefix="capri_giggle_") as temporary:
            raw = str(Path(temporary) / "raw.wav")
            speaker.render_silero(text, raw)
            subprocess.run([_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", raw,
                            "-af", "atempo=1.5", "-c:a", "pcm_s16le", str(path)],
                           check=True, capture_output=True, timeout=30,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        audio = decode(str(path))
        if not 2400 <= len(audio) <= 6 * 24000 or not np.isfinite(audio).all():
            raise ValueError("Invalid giggle audio")
        audio = micro_double(pitch_shift(audio, float(cfg.get("voice_shift", .8))),
                             float(cfg.get("voice_glitch", .45)))
        pieces.extend((audio, np.zeros(6000, dtype=np.float32)))
    preview = PROJECT_ROOT / "reports/fast-voice/emotions/giggles-faster-preview.wav"
    preview.parent.mkdir(parents=True, exist_ok=True)
    write_wav(str(preview), np.concatenate(pieces[:-1]))
    (bank / "generated.json").write_text(json.dumps({"source": "synthetic-silero",
        "voice": speaker.silero_voice, "processing": "raw", "variants": 3,
        "tempo": 1.5}, indent=2), encoding="utf-8")
    huff = root / "huff"
    huff.mkdir(parents=True, exist_ok=True)
    huff_speaker = Speaker(dict(raw_cfg, silero_pitch="low", voice_lively=False))
    huff_pieces = []
    for index, text in enumerate(("Хмф!", "Пф!"), 1):
        path = huff / f"generated_silero_{index}.wav"
        huff_speaker.render_silero(text, str(path))
        audio = micro_double(pitch_shift(decode(str(path)), float(cfg.get("voice_shift", .8))),
                             float(cfg.get("voice_glitch", .45)))
        huff_pieces.extend((audio, np.zeros(6000, dtype=np.float32)))
    write_wav(str(preview.with_name("huff-preview.wav")), np.concatenate(huff_pieces[:-1]))
    error = _edit_config(lambda data: data.update(voice_emotions_path=str(root)))
    if error:
        raise ValueError(error)
    print(f"Installed 3 faster giggles and 2 synthetic huffs; preview: {preview}")


if __name__ == "__main__":
    create()
