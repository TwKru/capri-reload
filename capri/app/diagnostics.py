"""Проверка собранного приложения без микрофона, модели и платных API."""
import json
import tempfile
from pathlib import Path


def voice_smoke(destination, engine="silero"):
    """Render Silero v5 directly: no microphone, playback, API or fallback TTS."""
    import time
    import wave

    from capri.audio.voice_service import SILERO_SHA256, Speaker
    from capri.config.defaults import DEFAULTS
    destination = Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    speaker = Speaker(dict(DEFAULTS,tts_engine=engine,voice_fx=0 if engine == "qwen_clone" else DEFAULTS["voice_fx"],
                           voice_shift=0 if engine == "qwen_clone" else DEFAULTS["voice_shift"]))
    samples = []
    for number, text in enumerate(("Слушаю…", "Открою поиск в браузере. Пока я думаю, окно остаётся на экране.")):
        path = destination/f"sample-{number}.wav"
        started = time.monotonic()
        if engine == "qwen_clone":
            speaker.render(text,str(path))
        else:
            speaker.render_silero(text,str(path))
        with wave.open(str(path),"rb") as audio:
            duration = audio.getnframes()/audio.getframerate()
            assert duration>.1
        samples.append({"render_seconds":round(time.monotonic()-started,3),"duration_seconds":round(duration,3)})
    if speaker.qwen is not None:
        speaker.qwen.close()
    identity = ({"profile_sha256":speaker.qwen.profile_id,"model":"Qwen3-TTS-0.6B-Q8","effects":"B"}
                if speaker.qwen is not None else {"speaker":speaker.silero_voice,"model_sha256":SILERO_SHA256})
    (destination/"voice.json").write_text(json.dumps({"engine":engine,**identity,
        "samples":samples},indent=2),encoding="utf-8")


def startup_smoke(destination):
    """Exercise native painting, desktop workers and GC without mic/API calls."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from capri.app.controller import BASE, DEFAULTS, Capri
    from capri.app.runtime_services import RuntimeServices
    from capri.desktop.avatar import Avatar
    from capri.ui.garbage_collection import GuiGarbageCollector
    from capri.ui.startup_animation import ScreenTransition

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    collector = GuiGarbageCollector(app)
    collector.timer.setInterval(1000)
    events = []
    with tempfile.TemporaryDirectory() as folder:
        cfg = dict(DEFAULTS, ai_mode="openai", personality=False)
        capri = Capri(cfg)
        avatar = Avatar(str(Path(BASE)/"assets"))
        runtime = capri.extensions = RuntimeServices(capri, avatar, folder)
        transition = ScreenTransition()
        transition.revealed.connect(avatar.summon)
        transition.finished.connect(events.append)
        transition.play("startup")
        QTimer.singleShot(12000, app.quit)
        try:
            app.exec()
            assert events == ["startup"], events
            assert not runtime.life.busy, "Desktop scan did not finish"
            result = {"transitions": events, "desktop_surfaces": len(runtime.life.surfaces),
                      "microphone_started": capri.listener is not None,
                      "native_platform": app.platformName()}
            (destination/"startup.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        finally:
            runtime.close()
            avatar.close()
            transition.close()
            collector.close()


def smoke(destination):
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from capri.ai.persona import personality_file as user_persona
    from capri.app import controller as main
    from capri.app.runtime_services import RuntimeServices
    from capri.desktop.avatar import Avatar
    from capri.ui.mainframe import Mainframe
    from capri.ui.theme import apply_theme
    destination = Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    app = QApplication([])
    apply_theme(app)
    for font in ("consola.ttf","consolab.ttf","consolai.ttf"):
        path = Path("C:/Windows/Fonts")/font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    assets = Path(main.BASE)/"assets"
    with tempfile.TemporaryDirectory() as folder:
        cfg = dict(main.DEFAULTS,ai_mode="openai",personality=False)
        capri = main.Capri(cfg)
        avatar = Avatar(str(assets))
        runtime = capri.extensions = RuntimeServices(capri,avatar,folder)
        runtime.install_hotkeys(lambda:None,app)
        window = Mainframe(runtime)
        runtime.window = window
        window.show()
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            window.grab().save(str(destination/f"mainframe-{index}.png"))
        result = {"tabs":window.tabs.count(),"sprites":len(avatar.anims),
                  "providers":{mode:main.configured_ai(dict(cfg,ai_mode=mode)).__class__.__name__ for mode in main.API_MODES},
                  "screen_watch":bool(cfg.get("screen_watch",False)),"agent_screen":bool(cfg.get("agent_screen",False)),
                  "registered_hotkeys":len(runtime.hotkeys.ids)}
        import os
        if os.name == "nt":
            from capri.desktop.window_companion import icon_surfaces, window_surfaces
            result["desktop_windows"] = len(window_surfaces())
            result["desktop_icons"] = len(icon_surfaces())
        runtime.close()
        avatar.close()
        user_persona.configure()
    (destination/"smoke.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
