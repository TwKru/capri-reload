"""Install the pinned CUDA 12.4 voice runtime beside the existing CPU runtime."""
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from capri.audio.qwen_backend import FOLDER
from capri.core.paths import PROJECT_ROOT, RESOURCE_ROOT

CUDA_FOLDER = "cuda-b12069"
ASSETS = {
    "llama-b12069-bin-win-cuda-12.4-x64.zip": "870d91ec1e87deea2ca347d2ccd3d99a2ee3dd3c76c9f3de7c33bf31f5f00d63",
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}
BASE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b12069/"


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file,"sha256").hexdigest()


def download(name, digest, cache):
    path = cache/name
    if not path.exists() or sha256(path) != digest:
        partial = path.with_suffix(".download")
        if os.name == "nt" and shutil.which("curl.exe"):
            subprocess.run(["curl.exe","--location","--fail","--retry","2","--connect-timeout","20",
                "--max-time","600","--silent","--show-error","--output",str(partial),BASE_URL+name],
                check=True,creationflags=0x08000000)
        else:
            request = urllib.request.Request(BASE_URL+name,headers={"User-Agent":"Capri-voice-setup"})
            with urllib.request.urlopen(request,timeout=60) as source,partial.open("wb") as output:
                shutil.copyfileobj(source,output,1024*1024)
        actual = sha256(partial)
        if actual != digest:
            raise ValueError("CUDA archive checksum mismatch: "+name)
        os.replace(partial,path)
    print("Verified "+name,flush=True)
    return path


def install(folder=FOLDER, cache=None):
    folder = Path(folder).resolve()
    cache = Path(cache or PROJECT_ROOT/"reports"/"gpu-voice"/"downloads")
    cache.mkdir(parents=True,exist_ok=True)
    folder.mkdir(parents=True,exist_ok=True)
    destination = (folder/CUDA_FOLDER).resolve()
    if destination.parent != folder:
        raise ValueError("Runtime path escapes voice folder")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        archives = list(pool.map(lambda item:download(*item,cache),ASSETS.items()))
    with tempfile.TemporaryDirectory(prefix="cuda-stage-",dir=folder) as temporary:
        stage = Path(temporary)
        for archive in archives:
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.infolist():
                    name = Path(entry.filename).name
                    if entry.is_dir() or Path(name).suffix.lower() not in (".exe",".dll"):
                        continue
                    target = stage/name
                    if target.exists():
                        raise ValueError("Duplicate CUDA runtime file: "+name)
                    with bundle.open(entry) as source,target.open("wb") as output:
                        shutil.copyfileobj(source,output)
        manifest = {path.name:sha256(path) for path in sorted(stage.iterdir())}
        if not {"llama-tts.exe","ggml-cuda.dll","cublas64_12.dll","cudart64_12.dll"} <= manifest.keys():
            raise ValueError("Incomplete CUDA voice runtime")
        expected_path = RESOURCE_ROOT/"bundled"/"qwen-tts-cuda-runtime.json"
        if expected_path.exists() and json.loads(expected_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("CUDA runtime differs from the application manifest")
        destination.mkdir(exist_ok=True)
        for path in stage.iterdir():
            os.replace(path,destination/path.name)
        (destination/"runtime-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("Installed CUDA runtime: "+str(destination),flush=True)


if __name__ == "__main__":
    install()
