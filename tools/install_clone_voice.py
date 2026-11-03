"""Install the approved local voice from pinned runtime/model files and private recordings."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from capri.audio.qwen_backend import FOLDER, MODEL_FILES
from capri.core.paths import PROJECT_ROOT, RESOURCE_ROOT


def verify(path, expected, size=None):
    if size is not None and path.stat().st_size != size:
        raise ValueError('Incorrect file size: ' + path.name)
    with path.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != expected:
            raise ValueError('Checksum mismatch: ' + path.name)


def install(source, references, folder=FOLDER):
    import numpy as np

    from capri.audio.clone_effects import spectral_profile
    from capri.audio.voice_service import decode, write_wav

    folder, source = Path(folder), Path(source)
    manifest = json.loads((RESOURCE_ROOT / 'bundled' / 'qwen-tts-runtime.json').read_text())
    for name, expected in manifest.items():
        verify(source / name, expected)
    for name, (size, expected) in MODEL_FILES.items():
        verify(source / name, expected, size)
    clips, seen = [], set()
    for path in references:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        audio = decode(str(path), sr=24000)
        if len(audio) < 2048 or not np.all(np.isfinite(audio)):
            raise ValueError('Invalid voice reference: ' + path.name)
        rms = np.sqrt(np.mean(audio ** 2))
        if rms > .001:
            audio = audio * min(2., .14 / rms)
        clips.extend((audio, np.zeros(int(24000 * .16), np.float32)))
    if not clips:
        raise ValueError('Нет записей в voicenew')
    reference = np.concatenate(clips[:-1])
    folder.mkdir(parents=True, exist_ok=True)
    for name in [*manifest, *MODEL_FILES]:
        target = folder / name
        if target.resolve() != (source / name).resolve():
            shutil.copy2(source / name, target)
    target = folder / 'voice-reference.wav'
    write_wav(str(target), reference, sr=24000)
    profile = {'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'spectrum': spectral_profile(reference).tolist(), 'recordings': len(seen),
               'version': 1}
    (folder / 'voice-profile.json').write_text(json.dumps(profile), encoding='utf-8')
    print(f'Голос B установлен: {len(seen)} записей, {len(reference)/24000:.1f} секунд образца')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=PROJECT_ROOT / 'models' / 'qwen-tts')
    parser.add_argument('--references', type=Path, default=PROJECT_ROOT / 'voicenew')
    args = parser.parse_args()
    references = sorted(path for path in args.references.iterdir()
                        if path.suffix.lower() in {'.wav', '.mp3', '.flac', '.ogg', '.m4a'})
    install(args.source, references)


if __name__ == '__main__':
    main()
