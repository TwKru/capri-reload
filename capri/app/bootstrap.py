"""Точка входа исходников и автономной сборки."""
import os
import sys


def main():
    from capri.app.restart import WAIT_FLAG, wait_for_previous
    if WAIT_FLAG in sys.argv:
        index = sys.argv.index(WAIT_FLAG)
        if index+1 >= len(sys.argv):
            raise ValueError("Не указан процесс предыдущей копии Капри")
        pid = sys.argv[index+1]
        del sys.argv[index:index+2]
        if not wait_for_previous(pid):
            return
    if "--setup-preview" in sys.argv:
        from tools.preview_setup_wizard import render
        render(sys.argv[sys.argv.index("--setup-preview")+1])
    elif "--voice-worker" in sys.argv:
        from capri.audio.kokoro_backend import main as run_voice_worker
        run_voice_worker(sys.argv[2:])
    elif "--smoke-test" in sys.argv:
        from capri.app.diagnostics import smoke
        smoke(sys.argv[sys.argv.index("--smoke-test")+1])
    elif "--startup-test" in sys.argv:
        from capri.app.diagnostics import startup_smoke
        startup_smoke(sys.argv[sys.argv.index("--startup-test")+1])
    elif "--clone-tts-test" in sys.argv:
        from capri.app.diagnostics import voice_smoke
        voice_smoke(sys.argv[sys.argv.index("--clone-tts-test")+1], engine="qwen_clone")
    elif "--tts-test" in sys.argv:
        from capri.app.diagnostics import voice_smoke
        voice_smoke(sys.argv[sys.argv.index("--tts-test")+1])
    elif os.name == "nt":
        if getattr(sys,"frozen",False):
            from pathlib import Path
            base = Path(sys.executable).parent
            from tools import install_vosk_model as download_model
            download_model.BASE = str(base)
            download_model.MODELS = str(base/"models")
            download_model.TARGET = str(base/"models"/download_model.NAME)
            if not download_model.ready():
                download_model.unpack(str(base/"bundled"/(download_model.NAME+".zip")))
        from capri.app.windows_application import run as run_windows
        run_windows()
    else:
        from capri.app.portable_application import main
        main()
