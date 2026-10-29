"""Capri Desktop's Kokoro blend, with local Russian phonemization and an isolated worker."""
import argparse
import atexit
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
import zipfile

PACK_URL = "https://github.com/lachydotmcg/capri-desktop/releases/download/voice-pack-1/capri-voice-1.zip"
PACK_SHA = "9fae085696d68a580d6b1a953d7b253129bfe506a2c016421b306b7237d3214c"
PACK_SIZE = 316041808
FOLDER = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Capri" / "voice" / "capri-voice-1"
HASHES = {
    "model.onnx": "b40f62b166ac8164b0627ef48a0b358eda0985e272fb03ef5252e7206305da11",
    "voices.bin": "af1739a37fc930ea92d7198dc231734f29a7f6789ff90d63e9e04687fc3cffcb",
    "tokens.txt": "6ebb6bb288f20f3ae8d004d3c2ca27697da27c037d75e81a60e2a6a663f95425",
}
PHONEME_MAP = str.maketrans({"ɭ": "l", "ɫ": "l", "ʑ": "zʲ", "ʐ": "ʒ", "y": "ɨ",
                            "ɱ": "m", "ɦ": "h", "ʉ": "u", '"': "", "͡": "", "͜": ""})


def verify_pack(folder=FOLDER):
    folder = Path(folder)
    for name, expected in HASHES.items():
        with (folder / name).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                raise ValueError("Kokoro voice pack checksum mismatch: " + name)


def install_pack(archive=None, folder=FOLDER):
    """Explicit setup only: authenticate before extracting data, never unpack native DLLs."""
    folder = Path(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capri_voice_install_", dir=folder.parent) as temp:
        if archive is None:
            archive = Path(temp) / "pack.zip"
            with urllib.request.urlopen(PACK_URL, timeout=60) as response, archive.open("wb") as output:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > PACK_SIZE:
                        raise ValueError("Voice archive exceeds the expected size")
                    output.write(block)
        archive = Path(archive)
        if archive.stat().st_size != PACK_SIZE:
            raise ValueError("Voice archive size mismatch")
        with archive.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != PACK_SHA:
                raise ValueError("Voice archive checksum mismatch")
        staging = Path(temp) / "staging"
        staging.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                name = PurePosixPath(entry.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in entry.filename or ":" in entry.filename:
                    raise ValueError("Unsafe voice archive path")
                if entry.is_dir():
                    continue
                if entry.filename not in HASHES and name.parts[0] != "licenses":
                    continue
                if entry.file_size > 330_000_000 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe voice archive entry")
                destination = staging.joinpath(*name.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        verify_pack(staging)
        folder.mkdir(parents=True, exist_ok=True)
        for file in staging.rglob("*"):
            if file.is_file():
                destination = folder / file.relative_to(staging)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(file, destination)


def adapt_phonemes(phonemes, vocab, russian=True):
    if russian:
        phonemes = phonemes.translate(PHONEME_MAP)
    return "".join(char for char in phonemes if char in vocab).strip()


class KokoroClient:
    def __init__(self, folder=FOLDER, threads=2):
        self.folder = Path(folder)
        self.threads = max(1, min(4, int(threads)))
        self.process = None
        self.results = None
        self.lock = threading.Lock()
        atexit.register(self.close)

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        if not all((self.folder / name).is_file() for name in HASHES):
            raise FileNotFoundError("Run setup_voice.bat to install the local Capri voice")
        executable = Path(sys.executable).with_name("python.exe")
        if not executable.exists():
            executable = Path(sys.executable)
        process = subprocess.Popen([str(executable), str(Path(__file__).resolve()), "--worker",
            "--parent", str(os.getpid()), "--threads", str(self.threads), "--folder", str(self.folder)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=0x08000000)
        self.process, self.results = process, queue.Queue()
        results = self.results

        def read():
            try:
                for line in process.stdout:
                    try:
                        results.put(json.loads(line))
                    except (ValueError, UnicodeError):
                        continue
            except (OSError, ValueError):
                pass
            finally:
                results.put(None)
        threading.Thread(target=read, daemon=True).start()

    def render(self, text, path, cancel=None, speed=1.0, timeout=45):
        deadline = time.monotonic() + timeout
        while not self.lock.acquire(timeout=.05):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Speech cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Local speech is busy")
        try:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Speech cancelled")
            self._start()
            payload = {"text": text, "path": str(Path(path).resolve()), "speed": speed}
            process, results = self.process, self.results
            def send():
                try:
                    process.stdin.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    results.put(None)
            threading.Thread(target=send, daemon=True).start()
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Speech cancelled")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Local speech timed out")
                try:
                    result = self.results.get(timeout=.05)
                except queue.Empty:
                    continue
                if result is None:
                    raise RuntimeError("Local speech worker exited")
                if result.get("ok") is not True:
                    raise RuntimeError("Local speech failed: " + str(result.get("error", "unknown")))
                return path
        except Exception:
            self.close()
            raise
        finally:
            self.lock.release()


def worker(folder, parent, threads):
    """Native code lives here; reuse the model, release it after five idle minutes."""
    import numpy as np
    import onnxruntime as ort
    import phonemizer
    import psutil
    from kokoro_onnx import Kokoro

    state = {"active": False, "last": time.monotonic()}
    owner = psutil.Process(parent)

    def watchdog():
        while True:
            time.sleep(2)
            if not owner.is_running() or (not state["active"] and time.monotonic() - state["last"] > 300):
                os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    verify_pack(folder)
    vocab = {}
    for line in (folder / "tokens.txt").read_text(encoding="utf-8").splitlines():
        symbol, index = line.rsplit(" ", 1)
        vocab[symbol] = int(index)
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    session = ort.InferenceSession(str(folder / "model.onnx"), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    voices = np.memmap(folder / "voices.bin", dtype="<f4", mode="r", shape=(54, 510, 1, 256))
    style = np.array(voices[53])
    del voices
    with tempfile.TemporaryDirectory(prefix="capri_kokoro_") as temp:
        style_path = str(Path(temp) / "style.npz")
        np.savez(style_path, capri=style)
        engine = Kokoro.from_session(session, style_path)
        engine.tokenizer.vocab = vocab
        engine.voices.close()
        for line in sys.stdin.buffer:
            state["active"] = True
            try:
                request = json.loads(line)
                text, output, speed = request["text"], Path(request["path"]), request["speed"]
                if (not isinstance(text, str) or not 0 < len(text) <= 12000 or output.suffix != ".wav"
                        or type(speed) not in (int, float) or not .5 <= speed <= 2):
                    raise ValueError("Invalid speech request")
                russian = any("а" <= c.lower() <= "я" or c.lower() == "ё" for c in text)
                phonemes = phonemizer.phonemize(text, language="ru" if russian else "en-us",
                    preserve_punctuation=True, with_stress=True, language_switch="remove-flags")
                phonemes = adapt_phonemes(phonemes, vocab, russian)
                if not phonemes:
                    raise ValueError("Text produced no supported phonemes")
                audio, rate = engine.create(phonemes, voice=style, speed=float(speed), is_phonemes=True)
                if not len(audio) or not np.isfinite(audio).all():
                    raise ValueError("Invalid generated audio")
                with wave.open(str(output), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
                result = {"ok": True}
            except Exception as error:
                result = {"ok": False, "error": type(error).__name__ + ": " + str(error)[:200]}
            finally:
                state["active"], state["last"] = False, time.monotonic()
            print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--archive")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--parent", type=int)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    args = parser.parse_args()
    if args.install:
        install_pack(args.archive, args.folder)
        print("Capri local voice installed and verified.")
    elif args.worker and args.parent:
        worker(args.folder, args.parent, max(1, min(4, args.threads)))
