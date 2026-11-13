"""Install an isolated cloning reference without overwriting the existing voice."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from capri.audio.qwen_backend import FOLDER


def install(audio_path, preset, source_url="", folder=FOLDER):
    if not re.fullmatch(r"[a-z0-9_-]{1,64}",preset) or preset == "default":
        raise ValueError("Укажи отдельное имя профиля: латинские буквы, цифры, дефис или подчёркивание")
    from capri.audio.clone_effects import spectral_profile
    from capri.audio.voice_service import decode, write_wav
    audio = decode(str(audio_path),sr=24000)
    if not 24000 <= len(audio) <= 24000*30 or not np.all(np.isfinite(audio)):
        raise ValueError("Нужен чистый образец длительностью от 1 до 30 секунд")
    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < .001:
        raise ValueError("Образец слишком тихий или пустой")
    audio = audio*min(2.,.14/rms)
    root = (Path(folder)/"presets").resolve()
    destination = (root/preset).resolve()
    if destination.parent != root:
        raise ValueError("Профиль выходит за папку presets")
    destination.mkdir(parents=True,exist_ok=True)
    reference = destination/"voice-reference.wav"
    write_wav(str(reference),audio,sr=24000)
    profile = {"sha256":hashlib.sha256(reference.read_bytes()).hexdigest(),
               "spectrum":spectral_profile(audio).tolist(),"recordings":1,"version":1,
               "preset":preset,"source_url":source_url,"duration_seconds":round(len(audio)/24000,3)}
    (destination/"voice-profile.json").write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Installed voice preset "+preset+": "+str(destination),flush=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio",type=Path)
    parser.add_argument("--preset",required=True)
    parser.add_argument("--source-url",default="")
    args = parser.parse_args()
    install(args.audio,args.preset,args.source_url)
