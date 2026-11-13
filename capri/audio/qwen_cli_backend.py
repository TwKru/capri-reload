"""Qwen CLI synthesis with the original B voice and isolated reference presets."""
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from capri.audio.qwen_backend import FOLDER, MODEL, PROJECTOR, QwenClient
from capri.core.paths import RESOURCE_ROOT

log = logging.getLogger("capri")
CUDA_FOLDER = "cuda-b12069"


class QwenCliClient(QwenClient):
    cache_revision = 'approved-cli-b-2'

    def __init__(self, threads=6, folder=FOLDER, device="cpu", context_size=4096,
                 voice_preset="default",processing="layered_b"):
        if not isinstance(voice_preset,str) or not re.fullmatch(r"[a-z0-9_-]{1,64}",voice_preset):
            raise ValueError("Неверное имя профиля голоса")
        if processing not in ("layered_b","clean"):
            raise ValueError("Неверная обработка голоса")
        reference_folder = Path(folder) if voice_preset == "default" else Path(folder)/"presets"/voice_preset
        super().__init__(threads=threads,folder=folder,reference_folder=reference_folder)
        self.voice_preset,self.processing = voice_preset,processing
        if device not in ("cpu","cuda","auto"):
            raise ValueError("Устройство голоса должно быть cpu, cuda или auto")
        self.device = ("cuda" if (self.folder/CUDA_FOLDER/"ggml-cuda.dll").is_file() else "cpu") if device == "auto" else device
        self.context_size = max(2048,min(8192,int(context_size)))
        self.runtime_folder = self.folder/CUDA_FOLDER if self.device == "cuda" else self.folder
        self._cuda_verified = False
        if self.device == "cuda":
            self.cache_revision = f"approved-cli-b-2-cuda-b12069-c{self.context_size}-nographs"
            # One short-lived TTS process per phrase: graph capture costs more than it saves here.
            self.process_env = dict(os.environ,GGML_CUDA_DISABLE_GRAPHS="1")
        if processing != "layered_b":
            self.cache_revision += "-"+processing

    def verify_files(self):
        super().verify_files()
        if self.device != "cuda" or self._cuda_verified:
            return
        manifest_path = RESOURCE_ROOT/"bundled"/"qwen-tts-cuda-runtime.json"
        if not manifest_path.is_file() or not (self.runtime_folder/"llama-tts.exe").is_file():
            raise FileNotFoundError("Не установлен CUDA-голос: python -m tools.install_qwen_cuda")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest.items():
            path = self.runtime_folder/name
            if path.parent != self.runtime_folder or not path.is_file():
                raise ValueError("Не найден файл CUDA-голоса: "+name)
            with path.open("rb") as file:
                if hashlib.file_digest(file,"sha256").hexdigest() != expected:
                    raise ValueError("CUDA voice checksum mismatch: "+name)
        probe = subprocess.run([str(self.runtime_folder/"llama-tts.exe"),"--list-devices"],
            cwd=self.runtime_folder,capture_output=True,text=True,timeout=30,
            creationflags=0x08000000 if os.name == "nt" else 0)
        if probe.returncode or "CUDA0" not in probe.stdout+probe.stderr:
            raise RuntimeError("CUDA-движок не видит видеокарту. Проверь драйвер NVIDIA или выбери qwen_device=cpu.")
        self._cuda_verified = True
        log.info("Голос Qwen: CUDA0, контекст %s, Q8; runtime b12069; CUDA Graphs отключены",self.context_size)

    def warmup(self, cancel):
        while not self.lock.acquire(timeout=.05):
            self._check_cancel(cancel)
        try:
            self._check_cancel(cancel)
            self.verify_files()
            from capri.audio.clone_effects import warmup_effects
            warmup_effects()
        finally:
            self.lock.release()

    def render(self, text, dst, cancel, volume=100):
        from capri.audio.clone_effects import process_layers, reduce_background
        from capri.audio.voice_service import _ffmpeg, decode, write_wav
        while not self.lock.acquire(timeout=.05):
            self._check_cancel(cancel)
        try:
            self._check_cancel(cancel)
            self.verify_files()
            with tempfile.TemporaryDirectory(prefix='capri_approved_voice_') as folder:
                raw = str(Path(folder) / 'raw.wav')
                # Preserve CLI defaults that generated B; the server uses another code path.
                frame_limit = 130 if len(text) <= 110 else min(512, max(130, len(text)*3))
                args = [str(self.runtime_folder / 'llama-tts.exe'), '-m', str(self.folder / MODEL),
                        '-mm', str(self.folder / PROJECTOR), '-p', text, '--tts-lang', 'ru',
                        '--tts-speaker-file', str(self.reference_folder / 'voice-reference.wav'), '--output', raw,
                        '-t', str(self.threads), '-ngl', 'all' if self.device == "cuda" else '0',
                        '-n', str(frame_limit), '--seed', '42']
                if self.device == "cuda":
                    args += ['--device','CUDA0','-c',str(self.context_size)]
                self.logfile = (self.folder / 'worker.log').open('w', encoding='utf-8')
                self.launch(args)
                deadline = time.monotonic() + 180
                try:
                    while self.process.poll() is None:
                        self._check_cancel(cancel)
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Approved voice synthesis timed out')
                        cancel.wait(.05)
                    if self.process.returncode:
                        raise RuntimeError('Ошибка генерации голоса B; подробности в worker.log')
                finally:
                    self.close()
                self._check_cancel(cancel)
                audio = decode(raw)
                processed = (process_layers(audio, self.target, _ffmpeg(), cancel)
                             if self.processing == "layered_b" else reduce_background(audio))
                self._check_cancel(cancel)
                write_wav(dst, processed, volume=volume)
                return dst
        finally:
            self.lock.release()
