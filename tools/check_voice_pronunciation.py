"""Render profanity probes and check their audio with the installed offline recognizer."""
import json
import time
from pathlib import Path

import numpy as np

from capri.audio.voice_service import Speaker, decode, write_wav
from capri.config.settings import CONFIG_PATH
from capri.core.paths import PROJECT_ROOT

PHRASES = ("Блядь, я тебя услышала.", "Вот это, конечно, пиздец.", "Ебать, неожиданно.",
           "Что за хуйня опять?", "Да ну нахуй, я всё проверю.", "Блять, ну и дела.")


def check():
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8-sig"))
    speaker = Speaker(dict(cfg, voice_volume=100))
    speaker._voice_context.mood = "angry"
    recognizer_model = Model(str(PROJECT_ROOT / cfg.get("vosk_model", "models/vosk-model-small-ru-0.22")))
    root = PROJECT_ROOT / "reports/fast-voice/pronunciation"
    root.mkdir(parents=True, exist_ok=True)
    rows, pieces = [], []
    for index, text in enumerate(PHRASES):
        path = root / f"phrase-{index}.wav"
        started = time.perf_counter()
        speaker.render_silero(text, str(path))
        elapsed = time.perf_counter() - started
        audio = decode(str(path))
        if not len(audio) or not np.isfinite(audio).all() or float(np.max(np.abs(audio))) < .01:
            raise ValueError("Missing or silent speech")
        speech = (decode(str(path), sr=16000) * 32767).astype("<i2").tobytes()
        recognizer = KaldiRecognizer(recognizer_model, 16000)
        transcripts = []
        if recognizer.AcceptWaveform(speech):
            transcripts.append(json.loads(recognizer.Result()).get("text", ""))
        transcripts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        row = {"text": text, "asr": " ".join(filter(None, transcripts)),
               "seconds": round(elapsed, 3), "audio_seconds": round(len(audio) / 24000, 3)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
        pieces.extend((audio, np.zeros(7200, dtype=np.float32)))
    write_wav(str(root / "profanity-preview.wav"), np.concatenate(pieces[:-1]))
    (root / "check.json").write_text(json.dumps({"recognizer": "vosk-small-ru",
        "note": "ASR can misrecognize words; this is not a phonetic listening assessment.",
        "phrases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    check()
