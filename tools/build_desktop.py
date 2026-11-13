"""Автономная сборка с Python/Qt; личные файлы никогда не включаются."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def build(dist_dir=BASE/"dist", clean=False):
    dist_dir = Path(dist_dir).resolve()
    sources = sorted([*BASE.glob("*.py"), *BASE.glob("capri/**/*.py"), *BASE.glob("tools/*.py")])
    before = {str(path.relative_to(BASE)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    args = [sys.executable,"-m","PyInstaller","--noconfirm","--windowed","--onedir",
            "--contents-directory",".","--name","Capri","--distpath",str(dist_dir),
            "--workpath",str(BASE/"build"),"--specpath",str(BASE/"build")]
    if clean:
        args += ["--clean"]
    for name in ("assets","bundled","media","third_party","docs"):
        if (BASE/name).exists():
            args += ["--add-data",f"{BASE/name}{os.pathsep}{name}"]
    for name in ("LICENSE","README.md"):
        if (BASE/name).exists():
            args += ["--add-data",f"{BASE/name}{os.pathsep}."]
    args += ["--collect-all","vosk","--collect-data","certifi"]
    args += ["--hidden-import","scipy.signal","--collect-data","torch"]
    if os.name == "nt":
        args += ["--collect-submodules","winrt","--collect-submodules","pycaw"]
    for name in ("tensorflow","matplotlib","pandas","IPython","tkinter","pytest"):
        args += ["--exclude-module",name]
    args += [str(BASE/"main.py")]
    subprocess.run(args,cwd=BASE,check=True)
    if any(hashlib.sha256((BASE/name).read_bytes()).hexdigest() != digest for name,digest in before.items()):
        raise RuntimeError("Исходники изменились во время сборки. Пересобери перед передачей пользователю.")
    platform = "Windows" if os.name == "nt" else "macOS" if sys.platform == "darwin" else "Linux"
    archive = dist_dir/f"Capri-{platform}.zip"
    root = dist_dir/"Capri"
    (root/"build-manifest.json").write_text(json.dumps(before,indent=2),encoding="utf-8")
    sys.path.insert(0,str(BASE))
    from capri.updates.source_updater import protected
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as bundle:
        for file in root.rglob("*"):
            if file.is_file() and not protected(file.relative_to(root)):
                bundle.write(file,file.relative_to(root))
    print(archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=BASE/"dist")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    build(args.dist_dir, args.clean)
