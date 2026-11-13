"""Persistent, CPU-only Qwen3-TTS native worker. All HTTP stays on loopback."""
import atexit
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from capri.core.paths import RESOURCE_ROOT

FOLDER = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Capri' / 'voice' / 'qwen3-b12069'
MODEL = 'Qwen3-TTS-12Hz-0.6B-Base.Q8_0.gguf'
PROJECTOR = 'Qwen3-TTS-12Hz-0.6B-Base.mmproj-Q8_0.gguf'
MODEL_FILES = {
    MODEL: (646211264, '59b28b4ab6a1c4e24e6701fc871a427c1fb3e8333f0ed5cebec3bb67a699ae8e'),
    PROJECTOR: (401129632, '202c1fbf3a0f00b7586ca45b8328d696cc6cd980c3798979eaa4fefe8efd8320'),
}


def speech_chunks(text, limit=110, first_limit=None):
    """Sentence boundaries first; every word survives long or unpunctuated replies."""
    current_limit = first_limit or limit
    for sentence in re.split(r'(?<=[.!?…])\s+', ' '.join(text.split())):
        while len(sentence) > current_limit:
            cut = sentence.rfind(' ', 0, current_limit + 1)
            cut = cut if cut > 0 else current_limit
            yield sentence[:cut]
            current_limit = limit
            sentence = sentence[cut:].lstrip()
        if sentence:
            yield sentence
            current_limit = limit


class QwenClient:
    def __init__(self, threads=6, folder=FOLDER, reference_folder=None):
        self.folder = Path(folder)
        self.reference_folder = Path(reference_folder) if reference_folder is not None else self.folder
        self.threads = max(1, min(6, int(threads)))
        self.process = None
        self.job = None
        self.logfile = None
        self.lock = threading.Lock()
        self.url = None
        self.key = None
        self.reference = None
        self.target = None
        profile = self.reference_folder / 'voice-profile.json'
        self.profile = json.loads(profile.read_text(encoding='utf-8')) if profile.exists() else {}
        self.profile_id = self.profile.get('sha256', 'missing')
        # Ignore system proxies even if Windows has a proxy configured.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        atexit.register(self.close)

    def close(self):
        """Also used to interrupt native synthesis. The next request restarts lazily."""
        process, self.process = self.process, None
        job, self.job = self.job, None
        logfile, self.logfile = self.logfile, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if job is not None:
            job.Close()
        if logfile is not None:
            logfile.close()

    def warmup(self, cancel):
        while not self.lock.acquire(timeout=.05):
            self._check_cancel(cancel)
        try:
            self._ensure(cancel)
            # Load DSP before the first uncached reply, outside the UI thread.
            from capri.audio.clone_effects import warmup_effects
            warmup_effects()
        finally:
            self.lock.release()

    def _request(self, route, payload=None, timeout=180):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(self.url + route, data=body, headers={
            'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with self.http.open(request, timeout=timeout) as response:
            return response.read()

    @staticmethod
    def _check_cancel(cancel):
        if cancel.is_set():
            raise InterruptedError('Voice interrupted')

    def _ensure(self, cancel):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self._check_cancel(cancel)
        self.verify_files()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.key = secrets.token_urlsafe(32)
        self.url = f'http://127.0.0.1:{port}'
        args = [str(self.folder / 'llama-server.exe'), '-m', str(self.folder / MODEL),
                '-mm', str(self.folder / PROJECTOR), '-t', str(self.threads), '-tb', str(self.threads),
                '-ngl', '0', '-np', '1', '-c', '2048', '--poll', '0', '--host', '127.0.0.1',
                '--port', str(port), '--no-webui', '--api-key', self.key]
        self.logfile = (self.folder / 'worker.log').open('w', encoding='utf-8')
        self.launch(args)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                self._check_cancel(cancel)
                if self.process.poll() is not None:
                    raise RuntimeError('Не удалось загрузить голос; подробности в worker.log')
                try:
                    self._request('/health', timeout=.5)
                    return
                except OSError:
                    cancel.wait(.1)
            raise TimeoutError('Voice worker startup timed out')
        except BaseException:
            self.close()
            raise

    def verify_files(self):
        if self.reference is not None:
            return
        if not self.profile or not (self.reference_folder / 'voice-reference.wav').exists():
            raise FileNotFoundError('Не установлен образец голоса: запусти setup_clone_voice.bat')
        for name, (size, _) in MODEL_FILES.items():
            if not (self.folder / name).exists() or (self.folder / name).stat().st_size != size:
                raise FileNotFoundError('Не установлена модель клонирования: ' + name)
        manifest = json.loads((RESOURCE_ROOT / 'bundled' / 'qwen-tts-runtime.json').read_text())
        for name, expected in manifest.items():
            with (self.folder / name).open('rb') as file:
                if hashlib.file_digest(file, 'sha256').hexdigest() != expected:
                    raise ValueError('Voice runtime checksum mismatch: ' + name)
        reference = (self.reference_folder / 'voice-reference.wav').read_bytes()
        if hashlib.sha256(reference).hexdigest() != self.profile_id:
            raise ValueError('Voice reference checksum mismatch')
        self.target = self.profile['spectrum']
        self.reference = base64.b64encode(reference).decode('ascii')

    def launch(self, args):
        flags = 0x08004000 if os.name == 'nt' else 0
        self.process = subprocess.Popen(args, cwd=Path(args[0]).parent, stdout=self.logfile,
                                        stderr=subprocess.STDOUT, creationflags=flags,env=getattr(self,"process_env",None))
        try:
            if os.name == 'nt':
                import win32job
                self.job = win32job.CreateJobObject(None, '')
                info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
                info['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
                win32job.AssignProcessToJobObject(self.job, int(self.process._handle))
        except BaseException:
            self.close()
            raise

    def render(self, text, dst, cancel, volume=100):
        import numpy as np

        from capri.audio.clone_effects import process_layers
        from capri.audio.voice_service import _ffmpeg, write_wav
        while not self.lock.acquire(timeout=.05):
            self._check_cancel(cancel)
        try:
            self._ensure(cancel)
            self._check_cancel(cancel)
            # Separate network wait lets stop() kill the worker promptly, including during vocoding.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='capri-tts-http') as pool:
                pending = pool.submit(self._request, '/tts', {
                    'input': text, 'lang': 'ru', 'speaker_ref_b64': self.reference,
                    'seed': 42, 'n_predict': min(512, max(130, len(text) * 3)),
                    'response_format': 'pcm', 'stream': False,
                })
                try:
                    while True:
                        self._check_cancel(cancel)
                        try:
                            raw = pending.result(timeout=.05)
                            break
                        except TimeoutError:
                            if pending.done():
                                raise
                except BaseException:
                    self.close()
                    raise
            self._check_cancel(cancel)
            audio = np.frombuffer(raw, dtype='<f4')
            if len(audio) < 2048 or not np.all(np.isfinite(audio)):
                raise ValueError('Voice worker returned invalid PCM')
            processed = process_layers(audio, self.target, _ffmpeg(), cancel)
            self._check_cancel(cancel)
            write_wav(dst, processed, volume=volume)
            return dst
        finally:
            self.lock.release()
