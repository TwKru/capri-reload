"""Cancellable Gradio client; remote output is raw and desktop DSP runs once."""
import logging
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("capri")


def transport_options():
    import httpx
    # SSE may legitimately be silent while the GPU generates speech.
    return {"timeout": httpx.Timeout(190, connect=15, write=15, pool=15)}


class ColabVoiceClient:
    cache_revision = "colab-qwen-raw-v1"

    def __init__(self, url, password, voice_id):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Нужна HTTPS-ссылка Colab/Gradio без пароля в адресе")
        if not password or not voice_id:
            raise ValueError("Не заданы пароль или идентификатор голоса Colab")
        self.url, self.password, self.profile_id = url.rstrip("/"), password, voice_id
        self.client = None
        self.job = None
        self.timed_api = False
        self.last_metrics = {}
        self.lock = threading.Lock()
        self.downloads = tempfile.TemporaryDirectory(prefix="capri_colab_")

    @staticmethod
    def check(cancel):
        if cancel.is_set():
            raise InterruptedError("Voice interrupted")

    def close(self):
        job = self.job
        if job is not None:
            job.cancel()
        client, self.client = self.client, None
        if client is not None:
            client.close()

    def warmup(self, cancel):
        while not self.lock.acquire(timeout=.05):
            self.check(cancel)
        try:
            self._connect(cancel)
        finally:
            self.lock.release()

    def _connect(self, cancel):
        self.check(cancel)
        if self.client is not None:
            return
        try:
            from gradio_client import Client
        except ImportError as error:
            raise RuntimeError("Установите requirements-colab-client.txt") from error
        client = Client(self.url, auth=("capri", self.password), verbose=False,
                        download_files=self.downloads.name, httpx_kwargs=transport_options())
        self.check(cancel)
        self.client = client
        try:
            identity = self._call("/identity", cancel)
            if identity.get("voice_id") != self.profile_id or identity.get("processing") != "raw":
                raise ValueError("Голос в сессии изменился: обновите подключение Colab")
            self.timed_api = "timings" in identity.get("features", [])
        except Exception:
            self.close()
            raise

    def _call(self, route, cancel, *args):
        self.job = self.client.submit(*args, api_name=route)
        deadline = time.monotonic() + (15 if route == "/identity" else 180)
        try:
            while not self.job.done():
                self.check(cancel)
                if time.monotonic() >= deadline:
                    raise TimeoutError("Colab не ответил за отведённое время")
                cancel.wait(.05)
            self.check(cancel)
            return self.job.result()
        finally:
            if not self.job.done():
                self.job.cancel()
            self.job = None

    def render(self, text, dst, cancel, volume=100):
        from capri.audio.voice_service import decode, write_wav
        started = time.perf_counter()
        while not self.lock.acquire(timeout=.05):
            self.check(cancel)
        try:
            acquired = time.perf_counter()
            self._connect(cancel)
            connected = time.perf_counter()
            if self.timed_api:
                result, server = self._call("/speak_timed", cancel, text)
            else:
                result, server = self._call("/speak", cancel, text), {}
            received = time.perf_counter()
            path = Path(result)
            self.check(cancel)
            if not path.resolve().is_relative_to(Path(self.downloads.name).resolve()):
                raise ValueError("Colab вернул файл за пределами папки загрузки")
            if not path.is_file() or path.stat().st_size > 24_000 * 2 * 120 + 1024:
                raise ValueError("Colab вернул некорректное аудио")
            try:
                audio = decode(str(path))
                self.check(cancel)
                write_wav(dst, audio, volume=volume)
                duration = len(audio) / 24000
                self.last_metrics = {"characters": len(text), "lock_seconds": acquired - started,
                                     "connect_seconds": connected - acquired,
                                     "request_seconds": received - connected,
                                     "decode_seconds": time.perf_counter() - received,
                                     "audio_seconds": duration, "total_seconds": time.perf_counter() - started}
                if server:
                    self.last_metrics["generation_seconds"] = float(server["generation_seconds"])
                    self.last_metrics["write_seconds"] = float(server["write_seconds"])
                    self.last_metrics["transport_queue_seconds"] = max(0, received - connected -
                        self.last_metrics["generation_seconds"] - self.last_metrics["write_seconds"])
                log.info("Colab voice timing: %s", {k: round(v, 3) for k, v in self.last_metrics.items()})
            finally:
                path.unlink(missing_ok=True)
        except Exception:
            self.close()
            raise
        finally:
            self.lock.release()


def configure(url, password):
    """Probe a live session before saving any app settings."""
    from gradio_client import Client

    from capri.config.settings import _edit_config
    # Validate transport before sending the password.
    ColabVoiceClient(url, password, "probe")
    with tempfile.TemporaryDirectory(prefix="capri_colab_probe_") as temporary:
        client = Client(url, auth=("capri", password), verbose=False,
                        download_files=temporary, httpx_kwargs=transport_options())
        identity = client.predict(api_name="/identity")
    if identity.get("processing") != "raw" or not identity.get("voice_id"):
        raise ValueError("Это не сервер голоса Капри")
    error = _edit_config(lambda cfg: cfg.update(tts_engine="colab", colab_tts_url=url,
                         colab_tts_password=password, colab_voice_id=identity["voice_id"]))
    if error:
        raise ValueError(error)
