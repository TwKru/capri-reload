"""Локальный GGUF: проверяемые загрузки и собственный llama-server на loopback."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from capri.ai.providers.openai_provider import APIError, OpenAI
from capri.core import cancellation

CATALOG = {
    "qwen3-4b": {"label":"Qwen3 4B · 2.5 ГБ", "repo":"unsloth/Qwen3-4B-Instruct-2507-GGUF",
        "rev":"a06e946bb6b655725eafa393f4a9745d460374c9", "file":"Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "sha":"3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597", "size":2497281120},
    "gemma4-e2b": {"label":"Gemma 4 E2B · 3.1 ГБ", "repo":"unsloth/gemma-4-E2B-it-GGUF",
        "rev":"0314792d7f1f7e229411f620751375812bb9faf2", "file":"gemma-4-E2B-it-Q4_K_M.gguf",
        "sha":"740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8", "size":3106738272},
    "gemma4-e4b": {"label":"Gemma 4 E4B · 4.6 ГБ", "repo":"ggml-org/gemma-4-E4B-it-GGUF",
        "rev":"a69f018d7678a2b9f5e705f8903d6fb29b9b25dc", "file":"gemma-4-E4B-it-Q4_0.gguf",
        "sha":"a555b900214b477d8880e7832e0b8925e139b0159640036b09fe472b6f2097f2", "size":4590807392},
}
EYES = {
    "gemma4-e2b": {"repo":"ggml-org/gemma-4-E2B-it-GGUF", "rev":"6938c58e698502037401a5f19f6905f2fb2f7dee", "file":"mmproj-gemma-4-E2B-it-Q8_0.gguf",
        "sha":"9406f99c16d68cda4f1f0552192dcc99021ea1fc6d2fd50b1dc3ccf30d04b292", "size":557368064},
    "gemma4-e4b": {"repo":"ggml-org/gemma-4-E4B-it-GGUF", "rev":"a69f018d7678a2b9f5e705f8903d6fb29b9b25dc", "file":"mmproj-gemma-4-E4B-it-Q8_0.gguf",
        "sha":"197f49a93027f9843772bd24a6a9e0be2a32a788de5a3def330e9c585d86edd1", "size":559874816},
}
SERVER_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-win-vulkan-x64.zip"
SERVER_SHA = "2c07574e7bde71321cb785282b20cc821e951132149eeceeea32ddebdbf0598e"


def download(url, destination, digest, size=0, progress=lambda value: None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < size + 256*1024**2:
        raise ValueError("Недостаточно места для модели")
    temporary = destination.with_suffix(destination.suffix+".partial")
    checksum, received = hashlib.sha256(), 0
    try:
        with cancellation.open_url(url, timeout=60) as response, temporary.open("wb") as stream:
            while True:
                cancellation.checkpoint()
                block = response.read(1024*1024)
                if not block:
                    break
                stream.write(block)
                checksum.update(block)
                received += len(block)
                progress(f"{received/1024**2:.0f} / {size/1024**2:.0f} МБ")
        if checksum.hexdigest() != digest or (size and size != received):
            raise ValueError("Размер или SHA256 загрузки не совпадает")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def install(base, name, vision=False, progress=lambda value: None):
    root = Path(base)/"models"/"gguf"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise ValueError("На этой платформе выбери свой llama-server и GGUF в настройках.")
    executable = root/"llama"/"llama-server.exe"
    if not executable.exists():
        archive = download(SERVER_URL, root/"llama.zip", SERVER_SHA, 32182350, progress)
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                target = (executable.parent/item.filename).resolve()
                if not target.is_relative_to(executable.parent.resolve()) or item.file_size > 1024**3:
                    raise ValueError("Небезопасный архив llama.cpp")
            bundle.extractall(executable.parent)
        archive.unlink()
    model = CATALOG[name]
    def fetch(info):
        destination = root/info["file"]
        # Переустановка также проверяет существующий файл.
        valid = destination.exists() and destination.stat().st_size == info["size"]
        if valid:
            checksum = hashlib.sha256()
            with destination.open("rb") as stream:
                for block in iter(lambda: stream.read(1024*1024), b""):
                    cancellation.checkpoint()
                    checksum.update(block)
            valid = checksum.hexdigest() == info["sha"]
        return destination if valid else download(f"https://huggingface.co/{info['repo']}/resolve/{info['rev']}/{info['file']}",destination,info["sha"],info["size"],progress)
    path = fetch(model)
    eyes = fetch(EYES[name]) if vision and name in EYES else None
    return {"llama_executable":str(executable),"llama_model":str(path),"llama_mmproj":str(eyes or "")}


class Server:
    def __init__(self, cfg):
        self.cfg, self.process, self.port = cfg, None, None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            executable, model = self.cfg.get("llama_executable", ""), self.cfg.get("llama_model", "")
            if not Path(executable).is_file() or not Path(model).is_file():
                raise APIError("Выбери или загрузи llama-server и GGUF в MAINFRAME → Локальные модели.")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0))
                self.port = sock.getsockname()[1]
            args = [executable,"-m",model,"--host","127.0.0.1","--port",str(self.port),"-c","8192","-ngl",str(self.cfg.get("llama_gpu_layers",99))]
            if self.cfg.get("llama_mmproj"):
                args += ["--mmproj",self.cfg["llama_mmproj"]]
            self.process = subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == "nt" else 0)
            try:
                for _ in range(240):
                    cancellation.checkpoint()
                    if self.process.poll() is not None:
                        raise APIError("llama-server завершился. Проверь GGUF и видеопамять.")
                    try:
                        with cancellation.open_url(f"http://127.0.0.1:{self.port}/health",timeout=1) as response:
                            if response.status == 200:
                                return
                    except OSError:
                        pass
                    cancellation.wait(.5)
                raise APIError("Истёк срок запуска llama-server")
            except BaseException:
                self.stop()
                raise

    def stop(self):
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


class LlamaClient:
    key = "local"

    def __init__(self, cfg):
        self.server, self.model = Server(cfg), Path(cfg.get("llama_model", "GGUF")).name

    def complete(self, messages, tokens=384, schema=None, images=None):
        self.server.start()
        rows = [dict(row) for row in messages]
        if images:
            if not self.server.cfg.get("llama_mmproj"):
                raise APIError("Для зрения GGUF выбери mmproj от той же модели.")
            rows[-1]["content"] = [{"type":"text","text":rows[-1]["content"]}] + [
                {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+image}} for image in images]
        payload = {"model":self.model,"messages":rows,"max_tokens":tokens,"temperature":.3,
                   "chat_template_kwargs":{"enable_thinking":False}}
        if schema:
            payload["response_format"] = {"type":"json_schema","json_schema":{"name":"step","schema":schema}}
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.port}/v1/chat/completions",
            data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
        try:
            with cancellation.open_url(request,timeout=120) as response:
                data = json.load(response)
            answer = data["choices"][0]["message"]["content"]
            if not answer:
                raise ValueError()
            return answer
        except (OSError, ValueError, KeyError, IndexError):
            cancellation.checkpoint()
            raise APIError("Локальная GGUF не вернула полный ответ.") from None


class LlamaAI(OpenAI):
    def __init__(self, cfg):
        self.client = LlamaClient(cfg)
        self.model, self.history, self.personality, self.economy = self.client.model, [], None, True
