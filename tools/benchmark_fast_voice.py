"""Compare uncached local synthesis of three Russian sentences without changing settings."""
import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np

from capri.audio.kokoro_backend import MASHA_FOLDER
from capri.audio.voice_service import Speaker

TEXT = ("Привет, я Капри, и я уже готова отвечать на твои вопросы. "
        "Сейчас я быстро проверю настройки и расскажу, что удалось найти. "
        "Если захочешь, мы сразу продолжим разговор и попробуем другие команды.")
EMOTION_TEXT = ("Ура, получилось, теперь я могу отвечать гораздо быстрее! "
                "Хочешь проверить, как я задаю вопросы и удивляюсь? "
                "Ну вот, а теперь можно немного выдохнуть и спокойно продолжить разговор…")


def benchmark(output, engines=None, emotions=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    text = EMOTION_TEXT if emotions else TEXT
    (output / "text.txt").write_text(text, encoding="utf-8")
    assert sum("а" <= c.lower() <= "я" for c in text) > 50
    if engines is None:
        engines = ["silero"]
        if (MASHA_FOLDER / "model.onnx").is_file():
            engines.append("kokoro")
    results = []
    for engine in engines:
        cfg = {"tts_engine": engine, "voice_fx": 0, "voice_shift": .8, "voice_glitch": .45,
               "voice_lively": emotions, "voice_volume": 100, "silero_voice": "baya", "silero_speed": 1.,
               "kokoro_voice": "masha", "kokoro_speed": 1.}
        speaker = Speaker(cfg)
        run = speaker.render_silero if engine == "silero" else speaker.render_kokoro
        trials = []
        try:
            for index in range(3):
                path = output / f"{engine}-{index}.wav"
                started = time.perf_counter()
                try:
                    run(text, str(path))
                except Exception as error:
                    print(engine + ": " + type(error).__name__, flush=True)
                    break
                elapsed = time.perf_counter() - started
                with wave.open(str(path), "rb") as audio:
                    duration = audio.getnframes() / audio.getframerate()
                    pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
                if duration < 3 or not len(pcm) or np.max(abs(pcm.astype(np.int32))) < 100:
                    raise ValueError("Output is empty or too short")
                row = {"seconds": round(elapsed, 3), "audio_seconds": round(duration, 3)}
                trials.append(row)
                print(json.dumps({"engine": engine, "trial": index, **row}), flush=True)
        finally:
            if speaker.kokoro:
                speaker.kokoro.close()
        results.append({"engine": engine, "trials": trials})
        (output / "benchmark.json").write_text(json.dumps({"text": text, "emotions": emotions, "results": results},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/fast-voice"))
    parser.add_argument("--engine", choices=("silero", "kokoro"), action="append")
    parser.add_argument("--emotions", action="store_true")
    args = parser.parse_args()
    benchmark(args.output, args.engine, args.emotions)
