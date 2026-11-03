"""Use the exact synthesis path that produced the user's approved B preview."""
import tempfile
import time
from pathlib import Path

from capri.audio.qwen_backend import MODEL, PROJECTOR, QwenClient


class QwenCliClient(QwenClient):
    cache_revision = 'approved-cli-b-2'

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
        from capri.audio.clone_effects import process_layers
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
                args = [str(self.folder / 'llama-tts.exe'), '-m', str(self.folder / MODEL),
                        '-mm', str(self.folder / PROJECTOR), '-p', text, '--tts-lang', 'ru',
                        '--tts-speaker-file', str(self.folder / 'voice-reference.wav'), '--output', raw,
                        '-t', str(self.threads), '-ngl', '0', '-n', str(frame_limit), '--seed', '42']
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
                processed = process_layers(audio, self.target, _ffmpeg(), cancel)
                self._check_cancel(cancel)
                write_wav(dst, processed, volume=volume)
                return dst
        finally:
            self.lock.release()
