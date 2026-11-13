"""Portable corpus preparation and Colab phrase-library export (no app credentials)."""
import argparse
import hashlib
import json
import shutil
import subprocess
import wave
import zipfile
from pathlib import Path

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".mp4", ".webm"}
UPSTREAM_REVISION = "022e286b98fbec7e1e916cb940cdf532cd9f488e"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(source, destination, ffmpeg=None):
    """Decode without trimming words; retain transcripts across repeated preparations."""
    import numpy as np
    source, destination = Path(source), Path(destination)
    paths = sorted(p for p in source.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS
                   and p.relative_to(source).parts[0] != "emotions")
    if not paths:
        raise ValueError(f"Нет записей в {source.resolve()}; добавьте аудио и повторите команду.")
    destination.mkdir(parents=True, exist_ok=True)
    audio_dir = destination / "audio"
    audio_dir.mkdir(exist_ok=True)
    previous = {}
    manifest = destination / "corpus.json"
    if manifest.exists():
        previous = {r["id"]: r for r in json.loads(manifest.read_text(encoding="utf-8"))["recordings"]}
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    records, seen = [], set()
    for path in paths:
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        identifier = digest[:24]
        target = audio_dir / f"{identifier}.wav"
        subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-y", "-i", str(path),
                        "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target)],
                       check=True, capture_output=True, timeout=180)
        with wave.open(str(target), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
        seconds = len(samples) / 24000
        rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0
        issues = []
        if not 1 <= seconds <= 15:
            issues.append("Нужен отдельный законченный фрагмент длиной 1–15 секунд.")
        if rms < .001:
            issues.append("Почти тишина.")
        if len(samples) and float(np.mean(abs(samples) >= .999)) > .01:
            issues.append("Возможен клиппинг: проверьте запись.")
        old = previous.get(identifier, {})
        sidecar = path.with_suffix(".txt")
        text = sidecar.read_text(encoding="utf-8-sig").strip() if sidecar.exists() else old.get("text", "")
        records.append({"id": identifier, "sha256": digest, "source": str(path.relative_to(source)),
                        "audio": f"audio/{identifier}.wav", "seconds": round(seconds, 3),
                        "text": text, "reviewed": bool(text and (sidecar.exists() or old.get("reviewed"))),
                        "issues": issues})
    write_json(manifest, {"version": 1, "sample_rate": 24000, "recordings": records})
    return records


def training_manifest(corpus, output):
    """Require reviewed text and valid recordings before extracting training codes."""
    corpus = Path(corpus).resolve()
    records = json.loads((corpus / "corpus.json").read_text(encoding="utf-8"))["recordings"]
    if not records or any(not r.get("reviewed") or not r.get("text", "").strip() or r.get("issues") for r in records):
        raise ValueError("Проверьте corpus.json: нужны точный text, reviewed=true и пустой issues у каждой записи.")
    reference = max(records, key=lambda r: min(r["seconds"], 10))["audio"]
    lines = []
    for record in records:
        audio = (corpus / record["audio"]).resolve()
        if not audio.is_relative_to(corpus) or not audio.is_file():
            raise ValueError("Аудио за пределами корпуса или файл отсутствует")
        lines.append(json.dumps({"audio": str(audio), "text": record["text"].strip(),
                                 "ref_audio": str(corpus / reference)}, ensure_ascii=False))
    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def transcribe(corpus, language=None):
    """Local-on-Colab ASR drafts; never mark guessed transcripts as reviewed."""
    from faster_whisper import WhisperModel
    corpus = Path(corpus)
    manifest = corpus / "corpus.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    model = WhisperModel("small", device="cuda", compute_type="float16")
    for record in content["recordings"]:
        if record.get("text"):
            continue
        segments, _ = model.transcribe(str(corpus / record["audio"]), language=language, beam_size=5)
        record["text"] = " ".join(s.text.strip() for s in segments)
        record["reviewed"] = False
        write_json(manifest, content)
    return content


def export_library(checkpoint, phrases, destination):
    """Generate raw 24 kHz speech; the desktop applies the approved voice effects once."""
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    destination = Path(destination)
    (destination / "audio").mkdir(parents=True, exist_ok=True)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tts = Qwen3TTSModel.from_pretrained(str(checkpoint), device_map="cuda:0", dtype=dtype,
                                       attn_implementation="sdpa")
    phrases = json.loads(Path(phrases).read_text(encoding="utf-8"))
    with (Path(checkpoint) / "model.safetensors").open("rb") as file:
        revision = hashlib.file_digest(file, "sha256").hexdigest()
    entries = []
    for text in dict.fromkeys(phrases):
        if not isinstance(text, str) or not text.strip():
            continue
        identifier = hashlib.sha256(text.encode("utf-8")).hexdigest()
        name = f"audio/{identifier}.wav"
        path = destination / name
        receipt = path.with_suffix(".json")
        expected = {"checkpoint": revision, "text": text}
        cached = receipt.exists() and json.loads(receipt.read_text(encoding="utf-8")) == expected and path.exists()
        if not cached:
            wavs, sr = tts.generate_custom_voice(text=text, speaker="capri", language="Russian")
            if sr != 24000:
                raise ValueError(f"Expected 24 kHz audio, got {sr}")
            temporary = path.with_suffix(".tmp.wav")
            sf.write(str(temporary), wavs[0], sr, subtype="PCM_16")
            temporary.replace(path)
            write_json(receipt, expected)
        entries.append({"text": text, "audio": name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        write_json(destination / "manifest.json", {"version": 1, "processing": "raw", "model": revision,
                                                    "entries": entries})
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        output.write(destination / "manifest.json", "manifest.json")
        for item in entries:
            output.write(destination / item["audio"], item["audio"])
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", type=Path, default=Path("voicenew"))
    prep.add_argument("--output", type=Path, default=Path("reports/voice-colab/corpus"))
    manifest = sub.add_parser("manifest")
    manifest.add_argument("corpus", type=Path)
    manifest.add_argument("output", type=Path)
    asr = sub.add_parser("transcribe")
    asr.add_argument("corpus", type=Path)
    asr.add_argument("--language", default=None)
    export = sub.add_parser("export")
    export.add_argument("checkpoint", type=Path)
    export.add_argument("phrases", type=Path)
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        records = prepare(args.source, args.output)
        print(f"Записей: {len(records)}, секунд: {sum(r['seconds'] for r in records):.1f}; {args.output}")
    elif args.command == "manifest":
        print(training_manifest(args.corpus, args.output))
    elif args.command == "transcribe":
        transcribe(args.corpus, args.language)
    elif args.command == "export":
        print(export_library(args.checkpoint, args.phrases, args.destination))


if __name__ == "__main__":
    main()
