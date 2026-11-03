"""Install the CPU-only Silero v5 runtime and activate Capri's voice profile."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable,"-m","pip","install","-r",str(root/"requirements-voice.txt")],check=True)
    from capri.audio.voice_service import silero_model
    from capri.config.defaults import DEFAULTS
    from capri.config.settings import _edit_config
    silero_model()
    keys = ("tts_engine","silero_voice","silero_pitch","silero_speed","voice_shift","voice_lively","voice_fx","voice_glitch")
    error = _edit_config(lambda data:data.update({key:DEFAULTS[key] for key in keys}))
    if error:
        raise RuntimeError(error)
    print("Silero TTS v5 installed. Restart Capri to apply the voice profile.")


if __name__ == "__main__":
    main()
