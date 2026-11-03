"""Проверки новых возможностей без сетевых вызовов и действий на рабочем столе."""
import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from capri.ai.providers.cloud_providers import CloudClient
from capri.app import controller as main
from capri.automation.desktop_agent import TaskRunner
from capri.core import cancellation
from capri.desktop.screen_capture import WatchGate, encode_frame
from capri.storage.conversation_memory import MemoryStore
from capri.storage.file_workspace import FileWorkspace
from capri.storage.task_store import JobStore


def step(action="done",**values):
    return dict({"action":action,"target":"","x":0,"y":0,"text":"","path":"","old":"","seconds":0},**values)


class FilesAndJobs(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root/"note.md"
        self.path.write_text("старый текст",encoding="utf-8")
        self.files = FileWorkspace([str(self.path)])
        self.store = JobStore(self.root/"jobs.sqlite")
        self.addCleanup(self.store.close)

    def runner(self,steps,**options):
        client = Mock()
        client.complete.side_effect = [json.dumps(item,ensure_ascii=False) for item in steps]
        runner = TaskRunner(self.store,self.files,Mock(),lambda:client,Mock(),Mock(),**options)
        runner.actions.handle.return_value.text = "Приложение открыто"
        runner.frames.get.return_value = {"image":"abc","width":100,"height":100,"rect":[0,0,100,100],"fingerprint":[1,2]}
        return runner,client

    def test_file_requires_grant_read_and_unchanged_contents(self):
        with self.assertRaises(ValueError):
            self.files.read("other.txt")
        with self.assertRaises(ValueError):
            self.files.write("note.md","новый")
        self.files.read("note.md")
        self.path.write_text("другая правка",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.files.write("note.md","новый")
        self.assertEqual(self.path.read_text(encoding="utf-8"),"другая правка")

    def test_write_backup_restore_and_unique_replace(self):
        self.files.replace("note.md","старый","новый")
        self.assertEqual(self.path.read_text(encoding="utf-8"),"новый текст")
        self.assertEqual(self.path.with_name("note.md.capri-backup").read_text(encoding="utf-8"),"старый текст")
        self.files.restore("note.md")
        self.assertEqual(self.path.read_text(encoding="utf-8"),"старый текст")
        with self.assertRaises(ValueError):
            self.files.replace("note.md","отсутствует","новый")

    def test_large_or_binary_files_are_not_sent(self):
        self.path.write_bytes(b"a"*1048577)
        with self.assertRaises(ValueError): self.files.read("note.md")
        self.path.write_bytes(b"abc\0def")
        with self.assertRaises(ValueError): self.files.read("note.md")

    def test_schedule_claim_is_atomic_and_repeat_is_future(self):
        ident = self.store.create("прочитай заметку",due=100,repeat=3600)
        self.assertEqual(self.store.claim_due(99),[])
        self.assertEqual(self.store.claim_due(100),[ident])
        self.assertEqual(self.store.claim_due(100),[])
        with patch("capri.storage.task_store.time.time",return_value=101): self.store.complete(ident,"готово")
        row = self.store.get(ident)
        self.assertEqual(row["status"],"scheduled")
        self.assertEqual(row["due"],3700)

    def test_resume_does_not_run_future_schedule_early(self):
        ident = self.store.create("позже",due=time.time()+3600)
        original = self.store.get(ident)["due"]
        self.store.update(ident,status="paused")
        self.store.resume(ident)
        self.assertEqual(self.store.get(ident)["due"],original)
        self.assertEqual(self.store.claim_due(),[])

    def test_restart_pauses_running_job_but_keeps_schedule_and_logs(self):
        ident = self.store.create("длительная задача")
        self.store.update(ident,status="running",progress=8)
        self.store.event(ident,"Выполнен шаг")
        reopened = JobStore(self.root/"jobs.sqlite")
        try:
            self.assertEqual(reopened.get(ident)["status"],"paused")
            self.assertEqual(reopened.get(ident)["progress"],8)
            self.assertEqual(reopened.log(ident)[0]["text"],"Выполнен шаг")
        finally: reopened.close()

    def test_runner_edits_selected_file_and_logs_result(self):
        ident = self.store.create("исправь файл")
        runner,client = self.runner([step("read_file",path="note.md"),step("write_file",path="note.md",text="исправлено"),step(text="Готово")])
        with patch("capri.automation.desktop_agent.cancellation.wait"): runner.run(ident)
        self.assertEqual(self.path.read_text(encoding="utf-8"),"исправлено")
        self.assertEqual(self.store.get(ident)["status"],"done")
        self.assertEqual(client.complete.call_count,3)
        self.assertTrue(self.store.log(ident))

    def test_cancelled_model_response_cannot_click_or_write(self):
        ident = self.store.create("исправь файл")
        runner,client = self.runner([])
        scope = cancellation.Scope()
        def response(*args,**kwargs):
            scope.cancel()
            return json.dumps(step("type",text="не печатать"))
        client.complete.side_effect = response
        with scope.bind(): runner.run(ident)
        runner.pointer.type_text.assert_not_called()
        self.assertEqual(self.store.get(ident)["status"],"paused")

    def test_no_vision_means_no_click_and_no_capture(self):
        ident = self.store.create("нажми кнопку")
        runner,_ = self.runner([step("click",target="кнопка",x=20,y=10)])
        runner.run(ident)
        runner.frames.get.assert_not_called()
        runner.pointer.click.assert_not_called()
        self.assertEqual(self.store.get(ident)["status"],"failed")

    def test_exact_blocked_step_needs_explicit_approval(self):
        ident = self.store.create("открой редактор")
        runner,client = self.runner([step("key",target="Send",text="ENTER"),step(text="Готово")],vision_enabled=lambda:True)
        with patch("capri.automation.desktop_agent.cancellation.wait"):
            runner.run(ident)
            self.assertEqual(self.store.get(ident)["status"],"awaiting_confirmation")
            runner.pointer.key.assert_not_called()
            runner.approve(ident)
            runner.run(ident)
        runner.pointer.key.assert_called_once_with("ENTER")
        self.assertEqual(self.store.get(ident)["status"],"done")

    def test_optional_plan_is_logged_before_any_action(self):
        ident = self.store.create("прочитай файл")
        runner,client = self.runner([{"plan":["Прочитать выбранный файл","Подвести итог"]},step(text="Готово")],plan_enabled=lambda:True)
        runner.run(ident)
        self.assertTrue(self.store.log(ident)[0]["text"].startswith("План:"))
        self.assertEqual(client.complete.call_count,2)

    def test_invisible_keyboard_and_dangerous_url_are_rejected(self):
        runner,_ = self.runner([])
        for action in (step("key",text="CTRL+L"),step("type",text="не печатать"),step("scroll",y=1),step("open_url",text="javascript:alert(1)"),step("open_app",target="powershell")):
            with self.assertRaises(ValueError): runner.execute(action,"задача")
        runner.pointer.key.assert_not_called()

    def test_agent_cannot_truncate_large_unseen_file(self):
        self.path.write_text("a"*14000,encoding="utf-8")
        runner,_ = self.runner([])
        self.assertIn("частично",runner.execute(step("read_file",path="note.md"),"исправь"))
        with self.assertRaises(ValueError): runner.execute(step("write_file",path="note.md",text="a"),"исправь")
        self.assertEqual(self.path.stat().st_size,14000)

    def test_note_sync_preserves_manual_text_and_forget(self):
        memory = MemoryStore(self.root/"memory.json")
        notes = self.root/"me.md"
        notes.write_text("# Обо мне\nМой велосипед синий\n",encoding="utf-8")
        memory.remember("Я живу в Томске")
        self.assertIn("велосипед",notes.read_text(encoding="utf-8"))
        self.assertIn("Томске",notes.read_text(encoding="utf-8"))
        self.assertEqual(memory.forget("велосипед"),"Забыла.")
        self.assertNotIn("велосипед",memory.context("велосипед"))

    def test_repeated_unproductive_action_pauses(self):
        ident = self.store.create("открой редактор")
        runner,client = self.runner([step("open_app",target="блокнот")]*4)
        with patch("capri.automation.desktop_agent.cancellation.wait"): runner.run(ident)
        self.assertEqual(self.store.get(ident)["status"],"paused")
        self.assertEqual(runner.actions.handle.call_count,3)

    def test_step_budget_pauses_and_resume_extends_it(self):
        ident = self.store.create("долго",max_steps=1)
        runner,_ = self.runner([step("wait",seconds=0)])
        with patch("capri.automation.desktop_agent.cancellation.wait"): runner.run(ident)
        self.assertEqual(self.store.get(ident)["status"],"paused")
        self.store.resume(ident)
        self.assertGreater(self.store.get(ident)["max_steps"],1)

    def test_history_expiry_and_manual_notes(self):
        memory = MemoryStore(self.root/"memory.json")
        with patch("capri.storage.conversation_memory.time.time",return_value=time.time()-8*86400): memory.record("старый вопрос","старый ответ")
        self.assertEqual(memory.recent(),[])
        self.assertEqual(json.loads(memory.path.read_text(encoding="utf-8"))["dialogue"],[])
        (self.root/"me.md").write_text("# Обо мне\nЛюбимый цвет — красный",encoding="utf-8")
        self.assertIn("красный",memory.context("мой цвет"))
        memory.clear()
        self.assertNotIn("красный",memory.context("мой цвет"))


class ApiAndScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_every_cloud_mode_skips_local_models_and_router(self):
        for provider in main.API_MODES:
            cfg = copy.deepcopy(main.DEFAULTS)
            cfg.update(ai_mode=provider)
            with patch("capri.app.controller.LocalAI") as local,patch("capri.app.controller.Speaker"),patch("capri.app.controller.make_glitch_sound"):
                capri = main.Capri(cfg)
                capri._background = Mock()
                capri._start_models()
                local.assert_not_called()
                capri._background.assert_not_called()
                self.assertIsNotNone(capri.router.api_client)

    def test_cloud_native_image_and_json_payloads(self):
        for provider in ("nvidia","deepseek","anthropic"):
            body = {"content":[{"type":"text","text":"ответ"}]} if provider=="anthropic" else {"choices":[{"message":{"content":"ответ"}}]}
            response = io.BytesIO(json.dumps(body).encode())
            with patch("capri.ai.providers.cloud_providers.cancellation.open_url",return_value=response) as opened:
                client = CloudClient({"ai_mode":provider,provider+"_api_key":"secret"})
                self.assertEqual(client.complete([{"role":"user","content":"экран"}],images=["abc"]),"ответ")
            request = opened.call_args.args[0]
            payload = json.loads(request.data)
            self.assertNotIn("secret",request.full_url)
            self.assertNotIn("secret",str(payload))
            self.assertIn("abc",json.dumps(payload))

    def test_missing_key_fails_before_network(self):
        for provider in ("nvidia","deepseek","anthropic"):
            with patch.dict(os.environ,{"NVIDIA_API_KEY":"","DEEPSEEK_API_KEY":"","ANTHROPIC_API_KEY":""}),patch("capri.ai.providers.cloud_providers.cancellation.open_url") as network:
                with self.assertRaises(Exception): CloudClient({"ai_mode":provider}).complete([])
                network.assert_not_called()

    def test_screens_are_small_jpeg_and_watch_skips_unchanged_frames(self):
        image = QImage(1920,1080,QImage.Format.Format_RGB32);image.fill(QColor("#991133"))
        frame = encode_frame(image,(0,0,1920,1080))
        self.assertEqual(frame["width"],960)
        self.assertTrue(base64.b64decode(frame["image"]).startswith(b"\xff\xd8"))
        gate = WatchGate()
        self.assertFalse(gate.due(False,False,now=0))
        self.assertTrue(gate.due(True,False,now=0))
        self.assertFalse(gate.due(True,False,now=30))
        self.assertTrue(gate.changed(frame));self.assertFalse(gate.changed(frame))

    def test_late_persona_edit_and_default_economy(self):
        from capri.ai.persona import personality_file as user_persona
        from capri.ai.persona.system_prompts import CHARACTER
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"personality.md"
            user_persona.ensure(path)
            user_persona.configure(path,"en")
            self.assertIn("SHORT",user_persona.system("SHORT"))
            self.assertNotIn(CHARACTER,user_persona.system("SHORT"))
            path.write_text("Индивидуальный характер",encoding="utf-8")
            self.assertIn("Индивидуальный",user_persona.system("SHORT"))
            self.assertIn("English",user_persona.system("SHORT"))
        user_persona.configure()

    def test_private_files_are_protected_and_excluded(self):
        from capri.updates import source_updater as updater
        from tools import package_source_release as make_release
        for name in ("me.md","personality.md","personality.backup.md","jobs.sqlite","jobs.sqlite-wal","jobs.sqlite-journal"):
            self.assertTrue(updater.protected(Path(name)))
            self.assertIn(name,make_release.SKIP_FILES)

    def test_parakeet_endpoint_adapter(self):
        import numpy as np

        from capri.audio.speech_recognition import ParakeetRecognizer
        engine = Mock();engine.create_stream.return_value.result.text = "капри привет"
        rec = ParakeetRecognizer("",engine)
        self.assertFalse(rec.AcceptWaveform((np.ones(1600,dtype=np.int16)*4000).tobytes()))
        for _ in range(6): self.assertFalse(rec.AcceptWaveform(bytes(3200)))
        self.assertTrue(rec.AcceptWaveform(bytes(3200)))
        self.assertEqual(json.loads(rec.Result())["text"],"капри привет")
        engine.decode_stream.assert_called_once()

    def test_mainframe_constructs_all_tabs_without_native_access(self):
        from capri.ai.persona import personality_file as user_persona
        from capri.app.runtime_services import RuntimeServices
        from capri.desktop.avatar import Avatar
        from capri.ui.mainframe import Mainframe
        with tempfile.TemporaryDirectory() as folder,patch("capri.app.controller.Speaker"),patch("capri.app.controller.make_glitch_sound"):
            cfg = copy.deepcopy(main.DEFAULTS); cfg["ai_mode"]="openai"
            capri = main.Capri(cfg)
            avatar = Avatar(str(Path(main.BASE)/"assets"))
            runtime = capri.extensions = RuntimeServices(capri,avatar,folder)
            runtime.install_hotkeys(lambda:None,self.app)
            window = Mainframe(runtime)
            self.assertEqual(window.tabs.count(),6)
            self.assertFalse(capri.cfg.get("screen_watch",False))
            self.assertFalse(capri.cfg.get("agent_screen",False))
            self.assertEqual(runtime.hotkeys.ids,{})
            ident = runtime.store.create("позже",due=time.time()+3600)
            window.refresh_tasks()
            window.pause_task()
            self.assertEqual(runtime.store.get(ident)["status"],"paused")
            window.cancel_task()
            self.assertEqual(runtime.store.get(ident)["status"],"cancelled")
            window.timer.stop();window.close();runtime.close();avatar.close()
        user_persona.configure()

    def test_gguf_router_and_chat_share_one_lazy_server(self):
        cfg = dict(main.DEFAULTS,ai_mode="llamacpp")
        with patch("capri.app.controller.LocalAI") as local,patch("capri.app.controller.Speaker"),patch("capri.app.controller.make_glitch_sound"):
            capri = main.Capri(cfg)
        local.assert_not_called()
        self.assertIs(capri.router.api_client,capri.ai.client)
        self.assertIsNone(capri.ai.client.server.process)
        capri._background = Mock()
        capri._start_models()
        capri._background.assert_not_called()

    def test_model_download_verifies_checksum_and_removes_partial(self):
        from capri.ai.providers.llama_cpp import download
        data = b"model data"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"model.gguf"
            with patch("capri.ai.providers.llama_cpp.cancellation.open_url",return_value=io.BytesIO(data)):
                download("https://example.org/model",path,hashlib.sha256(data).hexdigest(),len(data))
            self.assertEqual(path.read_bytes(),data)
            with patch("capri.ai.providers.llama_cpp.cancellation.open_url",return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError): download("https://example.org/model",path,"0"*64,len(data))
            self.assertEqual(path.read_bytes(),data)
            self.assertFalse(path.with_suffix(".gguf.partial").exists())

    def test_llama_archive_cannot_escape_model_directory(self):
        import zipfile

        from capri.ai.providers.llama_cpp import install
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/"malicious.zip"
            with zipfile.ZipFile(archive,"w") as bundle: bundle.writestr("../escape.exe",b"bad")
            with patch("capri.ai.providers.llama_cpp.download",return_value=archive):
                with self.assertRaises(ValueError): install(folder,"qwen3-4b")
            self.assertFalse((Path(folder)/"models"/"gguf"/"escape.exe").exists())

    def test_native_update_rejects_source_archive(self):
        from capri.updates import executable_updater as native_update
        with patch("capri.updates.executable_updater.cancellation.open_url",return_value=io.BytesIO(b'{"assets":[{"name":"sources.zip"}]}')):
            with self.assertRaises(ValueError): native_update.release()

    def test_global_key_parser_accepts_function_keys_and_rejects_unknown_modifier(self):
        from capri.desktop.window_companion import GlobalHotkeys
        self.assertEqual(GlobalHotkeys.parse("Ctrl+Alt+F8"),(0x4003,119))
        self.assertEqual(GlobalHotkeys.parse("Escape"),(0x4000,27))
        for key in ("Ctrl+Unknown+A","A","Ctrl+Ж"):
            with self.assertRaises(ValueError): GlobalHotkeys.parse(key)

    def test_native_update_stages_only_application_files(self):
        import zipfile

        from capri.updates import executable_updater as native_update
        data = io.BytesIO()
        with zipfile.ZipFile(data,"w") as bundle:
            bundle.writestr("Capri.exe",b"fake executable")
            bundle.writestr("config.json",b"private settings must not overwrite")
            bundle.writestr("jobs.sqlite",b"private jobs must not overwrite")
        content = data.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); base = root/"app"; stage = root/"update"
            base.mkdir();stage.mkdir()
            release = ({"tag_name":"v-test"},{"digest":"sha256:"+hashlib.sha256(content).hexdigest(),"browser_download_url":"https://example.org/Capri-Windows.zip"})
            with patch("capri.updates.executable_updater.release",return_value=release),patch("capri.updates.executable_updater.tempfile.mkdtemp",return_value=str(stage)),patch("capri.updates.executable_updater.cancellation.open_url",return_value=io.BytesIO(content)),patch("capri.updates.executable_updater.subprocess.Popen") as process:
                native_update.start(base,1234)
            manifest = json.loads((stage/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"],["Capri.exe",".native-version"])
            self.assertEqual(process.call_args.kwargs["creationflags"],0x08000000)
