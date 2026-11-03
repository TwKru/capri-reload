"""Точка входа исходников и автономной сборки."""
import os
import sys


def main():
    if "--voice-worker" in sys.argv:
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
            import json
            from pathlib import Path
            base = Path(sys.executable).parent
            if not (base/"config.json").exists():
                (base/"config.json").write_text(json.dumps({"ai_mode":"openai","local_ai":False,"first_start_mainframe":True}),encoding="utf-8")
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
