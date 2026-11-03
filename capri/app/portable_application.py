"""Ограниченный переносимый режим macOS/Linux: диалог, API, память и MAINFRAME."""
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from capri.ai.providers.cloud_providers import CloudAI
from capri.ai.providers.gemini_provider import Gemini
from capri.ai.providers.llama_cpp import LlamaAI
from capri.ai.providers.ollama_tools import OllamaClient
from capri.ai.providers.openai_provider import OpenAI
from capri.core import cancellation
from capri.desktop.avatar import Avatar
from capri.storage.conversation_memory import MemoryStore
from capri.ui.startup_animation import chip_icon
from capri.ui.theme import CyberInputDialog, apply_theme


class LocalChat(OpenAI):
    def __init__(self,cfg):
        self.client = OllamaClient(cfg)
        self.history, self.personality, self.economy = [], None, True
        self.model = self.client.model


class PortableActions:
    pending = choice = None

    def __init__(self):
        self.sites, self.apps = {}, {}

    def web(self,url):
        from urllib.parse import urlsplit
        if urlsplit(url).scheme not in ("http","https"):
            raise ValueError("Поддерживаются только http/https ссылки")
        webbrowser.open(url)

    def handle(self,text):
        name = re.sub(r"^открой\s+","",text,flags=re.IGNORECASE)
        apps = self.cfg.get("apps",{})
        executable = apps.get(name)
        if not executable:
            return None
        if not Path(executable).is_file() and not (sys.platform == "darwin" and executable.endswith(".app") and Path(executable).is_dir()):
            raise ValueError("Для приложения нужен путь к исполняемому файлу в config.json")
        if sys.platform == "darwin" and executable.endswith(".app"):
            subprocess.Popen(["open",executable])
        else:
            subprocess.Popen([executable])
        return SimpleNamespace(text="Приложение открыто")


class PortableCapri(QObject):
    subtitle = Signal(str)
    summon = Signal()
    mode = Signal(str,float)
    stop_motion = Signal()

    def __init__(self,base):
        super().__init__()
        self.base = Path(base)
        self.cfg = {"ai_mode":"openai","wake_words":["капри"],"apps":{}}
        path = self.base/"config.json"
        if path.exists():
            self.cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        self.ai, self.local = self.backend(), None
        self.memory = MemoryStore(self.base/"memory.json")
        self.actions = PortableActions(); self.actions.cfg = self.cfg
        self.jobs = cancellation.JobQueue(lambda:self.cancel_epoch)
        self.cancel_epoch, self.cancel_scopes = 0, set()
        self.speaking, self.voice_paused, self.last_request = False, True, ""
        self.extensions = None
        threading.Thread(target=self.worker,daemon=True).start()

    def backend(self):
        mode = self.cfg.get("ai_mode","openai")
        return {"openai":OpenAI,"gemini":Gemini,"nvidia":CloudAI,"deepseek":CloudAI,
                "anthropic":CloudAI,"llamacpp":LlamaAI,"local":LocalChat}.get(mode,OpenAI)(self.cfg)

    def save_settings(self,values):
        data = dict(self.cfg,**values)
        temporary = self.base/"config.json.tmp"
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temporary,self.base/"config.json")
        self.cfg.update(values)

    def set_ai_settings(self,mode,key,model):
        self.stop_listening()
        server = getattr(getattr(self.ai,"client",None),"server",None)
        if server:
            server.stop()
        self.save_settings({"ai_mode":mode,mode+"_api_key":key,mode+"_model":model})
        self.ai = self.backend()

    def text_command(self,text):
        self.last_request = text
        self.jobs.put(("text",text))

    def call_from_click(self):
        self.summon.emit()

    def toggle_voice(self,*args):
        self.subtitle.emit("В переносимом режиме доступен текстовый ввод.")

    def stop_listening(self):
        self.cancel_epoch += 1
        self.jobs.discard_before(self.cancel_epoch)
        for scope in list(self.cancel_scopes):
            scope.cancel()
        if self.extensions:
            self.extensions.store.pause_all()
            self.extensions.active = False
        self.stop_motion.emit()

    def worker(self):
        while True:
            job = self.jobs.get()
            # RequestScope регистрирует HTTP-соединения и отменяет ввод.
            scope = cancellation.Scope()
            self.cancel_scopes.add(scope)
            try:
                if getattr(job,"epoch",self.cancel_epoch) != self.cancel_epoch:
                    continue
                with scope.bind():
                    if job[0] in ("task","see","watch"):
                        self.extensions.process(job)
                        continue
                    text = job[1]
                    if self.extensions.command(text):
                        continue
                    reply = self.memory.command(text)
                    if reply is None:
                        self.ai.extra_memory = self.memory.context(text)
                        reply = self.ai.ask(text)
                        cancellation.checkpoint()
                        self.memory.record(text,reply)
                    self.summon.emit()
                    self.subtitle.emit(reply)
            except cancellation.RequestCancelled:
                pass
            except Exception as error:  # noqa: BLE001 -- граница фонового задания: ошибка передаётся в интерфейс
                self.subtitle.emit(str(error)[:500])
            finally:
                self.cancel_scopes.discard(scope)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    from capri.core.paths import APP_ROOT
    base = APP_ROOT
    avatar = Avatar(str(base/"assets"))
    capri = PortableCapri(base)
    from capri.app.runtime_services import RuntimeServices
    runtime = capri.extensions = RuntimeServices(capri,avatar,base)
    capri.subtitle.connect(avatar.set_subtitle)
    capri.summon.connect(avatar.summon)
    capri.mode.connect(avatar.set_mode)
    capri.stop_motion.connect(avatar.stop_motion)
    avatar.clicked.connect(capri.call_from_click)
    def ask():
        text,ok = CyberInputDialog.getText(None,"Капри","Команда или вопрос:")
        if ok and text.strip():
            capri.text_command(text.strip())
    menu = QMenu()
    for title,callback in (("Написать…",ask),("MAINFRAME",runtime.show),("Стоп",runtime.stop),
                           ("Позвать",avatar.summon),("Спрятать",avatar.vanish),("Выход",app.quit)):
        menu.addAction(title,callback)
    tray = QSystemTrayIcon(chip_icon()); tray.setContextMenu(menu); tray.show()
    tray.activated.connect(lambda reason:avatar.summon() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
    runtime.install_hotkeys(ask,app)
    app.aboutToQuit.connect(runtime.close)
    avatar.summon()
    runtime.show()
    sys.exit(app.exec())
