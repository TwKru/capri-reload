"""Диспетчер: типы, диапазоны и исполнение без произвольных цепочек команд."""
import io
import json
import unittest
import types
from unittest.mock import Mock, patch

from actions import Actions
from intent_router import Decision, IntentRouter


def decision(action="chat", target="", value=None, relative=False):
    return {"action": action, "target": target, "value": value, "relative": relative}


class RouterTests(unittest.TestCase):
    def test_json_schema_and_request_options(self):
        body = {"message": {"content": json.dumps(decision("volume", "discord", -10, True))}}
        with patch("intent_router.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as request:
            result = IntentRouter({}).ask("Потише дискорд")
        self.assertEqual(result.command(), "сделай discord тише на 10")
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["model"], "qwen3:0.6b")
        self.assertFalse(payload["think"])
        self.assertEqual(payload["format"]["properties"]["action"]["type"], "string")

    def test_invalid_decisions_cannot_be_executed(self):
        for data in (decision("shutdown"), decision("volume", value=1000), decision("gamma", value=0),
                     decision("open"), decision("open", "name\nsecond command"),
                     decision("volume", value=True), decision("volume", value=float("nan")),
                     {"action": "next"}, {**decision(), "shell": "anything"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Decision.parse(data)

    def test_failure_has_cooldown_and_does_not_block_every_question(self):
        router = IntentRouter({})
        with patch("intent_router.urllib.request.urlopen", side_effect=TimeoutError) as request:
            self.assertIsNone(router.ask("Первый запрос"))
            self.assertIsNone(router.ask("Второй запрос"))
            self.assertEqual(request.call_count, 1)

    def test_warming_router_does_not_delay_commands(self):
        router = IntentRouter({})
        router.warming = True
        with patch("intent_router.urllib.request.urlopen") as request:
            self.assertIsNone(router.ask("Запрос"))
            request.assert_not_called()

    def test_dispatch_uses_direct_handlers_and_keeps_target_as_data(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        app.media_next = Mock(return_value="next result")
        app.search = Mock(return_value="search result")
        app.run_chain = Mock()
        self.assertEqual(app.execute_decision(Decision("next")), "next result")
        app.media_next.assert_called_once()
        query = "новости и выключи компьютер"
        app.execute_decision(Decision("search", query))
        self.assertEqual(app.search.call_args.args[1].group("q"), query)
        app.run_chain.assert_not_called()
        self.assertIsNone(app.pending)

    def test_open_does_not_allow_paths_or_executable_commands(self):
        for target in (r"C:\Windows\cmd.exe", "cmd.exe", "name & command", "anything.bat"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                Decision("open", target).command()

    def test_questions_and_prohibitions_are_classified_but_never_executed(self):
        for phrase in ("Как выключить компьютер?", "не выключай музыку"):
            body = {"message": {"content": json.dumps(decision("music"))}}
            with patch("intent_router.urllib.request.urlopen",
                       return_value=io.BytesIO(json.dumps(body).encode())) as request:
                self.assertEqual(IntentRouter({}).ask(phrase).action, "chat")
                request.assert_called_once()

    def test_dialogue_context_is_sent_as_data(self):
        body = {"message": {"content": json.dumps(decision("hide"))}}
        with patch("intent_router.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(body).encode())) as request:
            result = IntentRouter({}).ask("нет", context={"awaiting_confirmation": True})
        self.assertEqual(result.action, "command")
        payload = json.loads(request.call_args.args[0].data)
        self.assertIn('awaiting_confirmation', payload["messages"][1]["content"])
        self.assertEqual(payload["messages"][-1]["content"], "нет")

    def test_explicit_volume_number_overrides_wrong_model_parameter(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        volume = Mock()
        volume.GetMasterVolume.return_value = 0.7
        session = types.SimpleNamespace(Process=types.SimpleNamespace(name=lambda: "chrome.exe"),
                                        SimpleAudioVolume=volume)
        with patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[session]), \
                patch("actions._endpoint") as endpoint:
            app.execute_decision(Decision("volume", "браузер", -10, True),
                                 original="Можешь поставить громкость браузера на тридцать?")
        volume.SetMasterVolume.assert_called_once_with(0.3, None)
        endpoint.assert_not_called()

    def test_hallucinated_app_target_is_not_used(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        with patch("pycaw.pycaw.AudioUtilities.GetAllSessions") as sessions:
            app.execute_decision(Decision("volume", "discord", -10, True), original="Сделай телеграм тише")
            sessions.assert_not_called()

    def test_gamma_value_is_taken_from_request(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        with patch("actions.gamma.set_gamma") as set_gamma:
            app.execute_decision(Decision("gamma", value=4.5), original="Можешь поставить гамму на два с половиной?")
            set_gamma.assert_called_once_with(2.5)


if __name__ == "__main__":
    unittest.main()
