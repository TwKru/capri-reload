"""Computer tool protocol and cancellation, without OS input or network."""
import copy
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from capri.ai.providers.computer_use import ComputerUseClient
from capri.ai.providers.openai_provider import APIError
from capri.app.runtime_services import RuntimeServices
from capri.automation.agent_input import PointerTools
from capri.automation.computer_use import ComputerUseRunner, validate_action
from capri.core import cancellation
from capri.storage.task_store import JobStore

FRAME = {"image":"synthetic-jpeg", "width":100, "height":50, "rect":[10,20,200,100], "fingerprint":[1,2]}


def call(*actions, checks=None):
    item = {"type":"computer_call", "call_id":"call_test", "actions":list(actions), "status":"completed"}
    if checks:
        item["pending_safety_checks"] = checks
    return [item]


def done(text="Готово"):
    return [{"type":"message","content":[{"type":"output_text","text":text}]}]


class ComputerUseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = JobStore(Path(folder.name)/"jobs.sqlite")
        self.addCleanup(self.store.close)
        self.cfg = {"openai_api_key":"test-key", "agent_screen":True, "computer_use_model":"test-model"}
        self.frames = Mock()
        self.frames.get.return_value = copy.deepcopy(FRAME)
        self.pointer = Mock()
        self.runner = ComputerUseRunner(self.store,self.frames,self.pointer,self.cfg)
        self.client_patch = patch("capri.automation.computer_use.ComputerUseClient")
        self.client = self.client_patch.start().return_value
        self.addCleanup(self.client_patch.stop)
        self.client.key = "test-key"
        delay = patch("capri.automation.computer_use.cancellation.wait")
        delay.start()
        self.addCleanup(delay.stop)

    def run_task(self, outputs, **limits):
        self.client.respond.side_effect = outputs
        ident = self.store.create("Введи привет в редактор",engine="computer_use",**limits)
        self.runner.run(ident)
        return ident

    def test_native_batch_then_screenshot_then_verified_final(self):
        ident = self.run_task([call({"type":"click","button":"left","x":20,"y":10},
                                   {"type":"type","text":"привет"}),done()])
        self.assertEqual(self.store.get(ident)["status"],"done")
        self.pointer.click.assert_called_once_with(50.,40.,"click")
        self.pointer.type_text.assert_called_once_with("привет")
        history = self.client.respond.call_args.args[0]
        self.assertEqual(history[-1]["type"],"computer_call_output")
        self.assertEqual(history[-1]["call_id"],"call_test")
        self.assertTrue(history[-1]["output"]["image_url"].startswith("data:image/jpeg;base64,"))
        persisted = json.dumps(self.store.get(ident))+json.dumps(self.store.log(ident))
        self.assertNotIn("synthetic-jpeg",persisted)
        self.assertNotIn("test-key",persisted)

    def test_all_native_actions_and_coordinate_mapping(self):
        for action in ({"type":"move","x":20,"y":10},
                       {"type":"scroll","x":20,"y":10,"scroll_x":50,"scroll_y":100},
                       {"type":"drag","path":[{"x":0,"y":0},{"x":99,"y":49}]},
                       {"type":"keypress","keys":["CTRL","a"]},
                       {"type":"double_click","x":20,"y":10},
                       {"type":"click","button":"middle","x":20,"y":10},
                       {"type":"wait"},{"type":"screenshot"}):
            self.runner.execute_action(action,FRAME)
        self.pointer.drag.assert_called_once_with([(10.,20.),(208.,118.)])
        self.pointer.scroll_pixels.assert_called_once_with(50,100)
        self.pointer.key.assert_called_once_with("CTRL+a")
        self.assertEqual(PointerTools.key_codes("CTRL+F12"),[17,123])

    def test_whole_batch_validated_before_first_click(self):
        ident = self.run_task([call({"type":"click","button":"left","x":20,"y":10},
                                   {"type":"keypress","keys":["unknown"]})])
        self.assertEqual(self.store.get(ident)["status"],"failed")
        self.pointer.click.assert_not_called()

    def test_no_screen_access_means_no_capture_no_api_no_input(self):
        self.cfg["agent_screen"] = False
        ident = self.run_task([])
        self.assertEqual(self.store.get(ident)["status"],"failed")
        self.frames.get.assert_not_called()
        self.client.respond.assert_not_called()
        self.assertFalse(self.pointer.mock_calls)

    def test_missing_key_does_not_capture_screen(self):
        self.client.key = ""
        ident = self.run_task([])
        self.frames.get.assert_not_called()
        self.assertEqual(self.store.get(ident)["status"],"failed")

    def test_cancelled_api_result_cannot_click(self):
        scope = cancellation.Scope()
        def respond(history):
            scope.cancel()
            return call({"type":"click","button":"left","x":1,"y":1})
        self.client.respond.side_effect = respond
        ident = self.store.create("Нажми кнопку",engine="computer_use")
        with scope.bind():
            self.runner.run(ident)
        self.assertEqual(self.store.get(ident)["status"],"paused")
        self.pointer.click.assert_not_called()

    def test_stop_in_middle_of_batch_preserves_completed_actions(self):
        scope = cancellation.Scope()
        self.pointer.click.side_effect = lambda *args:scope.cancel()
        self.client.respond.return_value = call({"type":"click","button":"left","x":1,"y":1},
                                               {"type":"type","text":"do not type"})
        ident = self.store.create("Открой поле",engine="computer_use")
        with scope.bind():
            self.runner.run(ident)
        self.pointer.type_text.assert_not_called()
        row = self.store.get(ident)
        self.assertEqual(row["status"],"paused")
        self.assertEqual(row["progress"],1)
        self.assertEqual(json.loads(row["observations"])[-1]["actions"],["click"])

    def test_safety_check_is_not_automatically_acknowledged(self):
        checks = [{"id":"sc1","code":"test","message":"Confirm this action"}]
        ident = self.run_task([call({"type":"type","text":"hello"},checks=checks)])
        self.assertEqual(self.store.get(ident)["status"],"awaiting_confirmation")
        self.pointer.type_text.assert_not_called()
        self.runner.approve(ident)
        self.client.respond.side_effect = [done()]
        self.runner.run(ident)
        self.assertEqual(self.store.get(ident)["status"],"done")
        self.assertEqual(self.client.respond.call_args.args[0][-1]["acknowledged_safety_checks"],checks)
        self.pointer.type_text.assert_called_once_with("hello")

    def test_changed_screen_cannot_execute_approved_old_step(self):
        ident = self.run_task([call({"type":"click","button":"left","x":1,"y":1},
                                   checks=[{"id":"sc1"}])])
        self.runner.approve(ident)
        self.frames.get.return_value = dict(FRAME,fingerprint=[8,8])
        self.runner.run(ident)
        self.pointer.click.assert_not_called()
        self.assertEqual(self.store.get(ident)["status"],"failed")

    def test_action_budget_can_finish_on_last_action(self):
        ident = self.run_task([call({"type":"type","text":"hello"}),done()],max_steps=1)
        self.assertEqual(self.store.get(ident)["status"],"done")
        self.assertEqual(self.store.get(ident)["progress"],1)

    def test_action_budget_pauses_partway_through_batch(self):
        ident = self.run_task([call({"type":"type","text":"one"},{"type":"type","text":"two"})],max_steps=1)
        self.assertEqual(self.store.get(ident)["status"],"paused")
        self.pointer.type_text.assert_called_once_with("one")
        self.store.resume(ident)
        self.assertGreater(self.store.get(ident)["max_steps"],1)

    def test_time_budget_expires_before_input(self):
        def respond(history):
            clock.return_value = 100
            return call({"type":"click","button":"left","x":1,"y":1})
        ident = self.store.create("Нажми кнопку",seconds=15,engine="computer_use")
        with patch("capri.automation.computer_use.time.monotonic",return_value=0) as clock:
            self.client.respond.side_effect = respond
            self.runner.run(ident)
        self.pointer.click.assert_not_called()
        self.assertEqual(self.store.get(ident)["status"],"paused")

    def test_revoking_screen_during_response_stops_input(self):
        def respond(history):
            self.cfg["agent_screen"] = False
            return call({"type":"type","text":"no"})
        self.client.respond.side_effect = respond
        ident = self.store.create("Введи текст",engine="computer_use")
        self.runner.run(ident)
        self.pointer.type_text.assert_not_called()

    def test_voice_and_text_route_to_native_engine(self):
        runtime = Mock()
        runtime.store = self.store
        for command in ("управляй компьютером: открой редактор", "computer_use: открой редактор"):
            self.assertTrue(RuntimeServices.command(runtime,command))
            row = self.store.list()[0]
            self.assertEqual(row["request"],"открой редактор")
            self.assertEqual(row["engine"],"computer_use")

    def test_invalid_coordinates_and_unbounded_actions_rejected(self):
        for action in ({"type":"click","button":"left","x":100,"y":1},
                       {"type":"move","x":True,"y":1}, {"type":"shell","command":"anything"},
                       {"type":"drag","path":[]}, {"type":"type","text":"x"*10001},
                       {"type":"scroll","x":1,"y":1,"scroll_x":0,"scroll_y":99999}):
            with self.assertRaises(ValueError):
                validate_action(action,FRAME)


class TransportAndStorageTests(unittest.TestCase):
    def test_native_protocol_is_stateless_and_uses_separate_model(self):
        client = ComputerUseClient({"openai_api_key":"test-key", "openai_model":"chat", "computer_use_model":"computer"})
        data = io.BytesIO(json.dumps({"status":"completed","output":done()}).encode())
        with patch("capri.ai.providers.computer_use.cancellation.open_url",return_value=data) as transport:
            client.respond([{"role":"user","content":"test"}])
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload["model"],"computer")
        self.assertEqual(payload["tools"],[{"type":"computer"}])
        self.assertFalse(payload["store"])
        self.assertNotIn("test-key",json.dumps(payload))

    def test_invalid_api_response_fails_without_claiming_success(self):
        client = ComputerUseClient({"openai_api_key":"test-key"})
        with patch("capri.ai.providers.computer_use.cancellation.open_url",return_value=io.BytesIO(b'{"status":"incomplete"}')):
            with self.assertRaises(APIError):
                client.respond([])

    def test_existing_database_migrates_without_losing_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"jobs.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, due REAL NOT NULL, repeat REAL NOT NULL DEFAULT 0, max_steps INTEGER NOT NULL, seconds INTEGER NOT NULL, progress INTEGER NOT NULL DEFAULT 0, observations TEXT NOT NULL DEFAULT '[]', result TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL)")
            connection.execute("INSERT INTO jobs(request,status,due,max_steps,seconds,created,updated) VALUES('old job','scheduled',1,20,60,1,1)")
            connection.commit()
            connection.close()
            store = JobStore(path)
            try:
                self.assertEqual(store.get(1)["request"],"old job")
                self.assertEqual(store.get(1)["engine"],"default")
                ident = store.create("new job",engine="computer_use")
                self.assertEqual(store.get(ident)["engine"],"computer_use")
            finally:
                store.close()
