"""Measure Colab synthesis, transfer/queue overhead and warm/cold client latency."""
import argparse
import json
import threading
from pathlib import Path

from capri.audio.colab_backend import ColabVoiceClient
from capri.config.settings import CONFIG_PATH


def benchmark(output, texts):
    cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8-sig"))
    if not cfg.get("colab_tts_url"):
        raise ValueError("Сначала подключите голос Colab")
    client = ColabVoiceClient(cfg["colab_tts_url"], cfg["colab_tts_password"], cfg["colab_voice_id"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()
    rows = []
    try:
        for index, text in enumerate(texts):
            try:
                client.render(text, str(output / f"sample-{index}.wav"), cancel)
            except Exception as error:
                rows.append({"sample": index, "error": type(error).__name__})
                print(f"Не удалось выполнить замер: {type(error).__name__}", flush=True)
                break
            row = {k: round(v, 3) for k, v in client.last_metrics.items()}
            row["rtf"] = round(row["total_seconds"] / max(.001, row["audio_seconds"]), 3)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=True), flush=True)
    except KeyboardInterrupt:
        cancel.set()
        raise
    finally:
        client.close()
        client.downloads.cleanup()
        (output / "timings.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/colab-speed"))
    parser.add_argument("--text", action="append")
    args = parser.parse_args()
    benchmark(args.output, args.text or ["Привет! Я Капри.",
              "Сейчас проверю скорость голоса и расскажу, что получилось."])
