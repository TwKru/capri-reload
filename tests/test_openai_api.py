"""API-only: запросы, ошибки, отмена и отсутствие запуска локальных моделей."""
import copy
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLineEdit

from capri.ai.intent_router import COMMAND_SCHEMA, IntentRouter
from capri.ai.providers.openai_provider import ECONOMY_SYSTEM, OpenAI, ResponsesClient
from capri.ai.request_planner import economy_plan
from capri.app import controller as main
from capri.core import cancellation
from capri.ui.dialogs.ai_settings import AIDialog


def response(text, status="completed"):
    return io.BytesIO(json.dumps({"status": status, "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": text}]}]}).encode())


class OpenAIRequestTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"ai_mode": "openai", "openai_api_key": "test-secret", "openai_model": "gpt-6-luna"}

    def test_responses_request_keeps_bounded_history_and_web_evidence(self):
        ai = OpenAI(self.cfg)
        with patch("capri.core.cancellation.urllib.request.urlopen", side_effect=lambda *a, **k: response("Ответ.")) as request:
            for index in range(9):
                ai.ask(f"Вопрос {index}", web_context=[{"text": "Проверенный факт"}])
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(sent.get_header("Authorization"), "Bearer test-secret")
        body = json.loads(sent.data)
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertFalse(body["store"])
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertIn("Проверенный факт", body["input"][0]["content"])
        self.assertEqual(body["input"][-1]["content"], "Вопрос 8")
        self.assertLessEqual(len(ai.history), 12)
        self.assertEqual(ai.history[0]["role"], "user")

    def test_router_uses_strict_schema_and_preserves_command_guards(self):
        router = IntentRouter(self.cfg)
        raw = json.dumps({"action": "music", "target": "", "value": None, "relative": False})
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response(raw)) as request:
            self.assertEqual(router.ask("Как выключить компьютер?").action, "chat")
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["text"]["format"]["schema"], COMMAND_SCHEMA)
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("keep_alive", body)
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            router.warmup()
            request.assert_not_called()

    def test_missing_key_and_http_errors_do_not_pollute_history_or_leak_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            ai = OpenAI({})
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            self.assertIn("ключ", ai.ask("привет"))
            request.assert_not_called()
        ai = OpenAI(self.cfg)
        for status in (401, 403, 429, 500):
            error = urllib.error.HTTPError("https://api.openai.com/v1/responses", status,
                "test-secret", {}, io.BytesIO(b"test-secret"))
            with patch("capri.core.cancellation.urllib.request.urlopen", side_effect=error):
                answer = ai.ask("привет")
            self.assertNotIn("test-secret", answer)
            self.assertEqual(ai.history, [])

    def test_incomplete_and_empty_answers_are_not_saved(self):
        ai = OpenAI(self.cfg)
        for text, status in (("Незавершённый", "incomplete"), ("", "completed")):
            with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response(text, status)):
                ai.ask("вопрос")
            self.assertEqual(ai.history, [])

    def test_network_failure_is_readable(self):
        with patch("capri.core.cancellation.urllib.request.urlopen", side_effect=TimeoutError()):
            self.assertIn("интернет", OpenAI(self.cfg).ask("вопрос"))

    def test_cancelled_request_does_not_send_or_commit_history(self):
        scope = cancellation.Scope()
        ai = OpenAI(self.cfg)
        def cancel(*args, **kwargs):
            scope.cancel()
            return response("Запоздалый ответ")
        with scope.bind(), patch("capri.core.cancellation.urllib.request.urlopen", side_effect=cancel):
            with self.assertRaises(cancellation.RequestCancelled):
                ai.ask("вопрос")
        self.assertEqual(ai.history, [])

    def test_environment_key_is_supported(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "environment-secret"}):
            self.assertEqual(ResponsesClient({}).key, "environment-secret")

    def test_economy_bounds_history_output_and_preserves_current_question(self):
        ai = OpenAI(self.cfg)
        question = "Длинный текущий запрос " * 500
        with patch("capri.core.cancellation.urllib.request.urlopen", side_effect=lambda *a, **k: response("Ответ " * 500)) as request:
            ai.ask("Старый текст " * 1000)
            ai.ask(question)
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["max_output_tokens"], 160)
        self.assertEqual(body["input"][-1]["content"], question)
        self.assertLessEqual(sum(len(m["content"]) for m in body["input"][1:-1]), 1600)
        self.assertLess(len(ECONOMY_SYSTEM), 600)
        self.assertEqual(len(ai.history), 2)
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response("Подробный ответ")) as request:
            ai.ask("Объясни подробнее по шагам")
        self.assertEqual(json.loads(request.call_args.args[0].data)["max_output_tokens"], 384)

    def test_output_limit_keeps_complete_sentence_without_retry(self):
        ai = OpenAI(self.cfg)
        raw = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
               "output": [{"type": "message", "content": [{"type": "output_text",
                   "text": "Законченное предложение. Незавершённое"}]}]}
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(raw).encode())) as request:
            self.assertEqual(ai.ask("Вопрос"), "Законченное предложение.")
        self.assertEqual(request.call_count, 1)


class APIModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_capri(self, mode="openai"):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(ai_mode=mode, openai_api_key="test-secret")
        with patch("capri.app.controller.Actions"), patch("capri.app.controller.Speaker"), patch("capri.app.controller.make_glitch_sound"):
            return main.Capri(cfg)

    def prepare_request(self):
        capri = self.make_capri()
        capri.actions.handle.return_value = None
        capri.actions.handle_conversation.return_value = None
        capri.actions.pending = capri.actions.choice = None
        capri.reload_config_if_changed = Mock()
        capri.say = Mock(return_value=False)
        capri.web = Mock()
        capri.web.ask.return_value = []
        return capri

    def run_text(self, capri, text):
        capri.text_command(text)
        capri._process(capri.jobs.get_nowait())

    def test_known_command_and_confirmation_spend_zero_api_tokens(self):
        for text, pending in (("громкость браузера 20", None), ("да", lambda: None)):
            capri = self.prepare_request()
            capri.actions.pending = pending
            capri.actions.handle.return_value = main.Reply("Готово.")
            with patch("capri.core.cancellation.urllib.request.urlopen") as request:
                self.run_text(capri, text)
            request.assert_not_called()
            capri.actions.handle.assert_called_once_with(text)

    def test_local_time_question_keeps_fast_handler_without_web_or_api(self):
        capri = self.prepare_request()
        capri.actions.is_fast_command.return_value = True
        capri.actions.handle.return_value = main.Reply("Сейчас двенадцать часов.")
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            self.run_text(capri, "какая сегодня дата")
        request.assert_not_called()
        capri.web.ask.assert_not_called()
        capri.actions.handle.assert_called_once()

    def test_clear_question_uses_only_one_api_request(self):
        capri = self.prepare_request()
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response("Из-за рассеяния света.")) as request:
            self.run_text(capri, "Почему небо голубое?")
        self.assertEqual(request.call_count, 1)
        capri.actions.handle.assert_not_called()
        capri.web.ask.assert_not_called()

    def test_current_news_uses_one_answer_call_and_bounded_evidence(self):
        capri = self.prepare_request()
        capri.web.ask.return_value = [{"title": "Источник", "url": "https://example.com", "text": "Новости. " * 2000}]
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response("Краткие новости.")) as request:
            self.run_text(capri, "Какие новости сегодня?")
        self.assertEqual(request.call_count, 1)
        capri.web.ask.assert_called_once()
        body = json.loads(request.call_args.args[0].data)
        self.assertLess(len(body["input"][0]["content"]), 2500)
        self.assertEqual(body["max_output_tokens"], 160)

    def test_ready_weather_spends_zero_api_tokens(self):
        capri = self.prepare_request()
        capri.web.ask.return_value = [{"title": "Погода", "url": "https://example.com", "text": "Сейчас пять градусов.",
                                        "answer": "Сейчас пять градусов."}]
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            self.run_text(capri, "Какая погода в Новосибирске?")
        request.assert_not_called()
        capri.say.assert_called_once_with("Сейчас пять градусов.")

    def test_unknown_command_keeps_ai_routing_and_runs_parser_once(self):
        capri = self.prepare_request()
        raw = json.dumps({"action": "next", "target": "", "value": None, "relative": False})
        capri.actions.execute_decision.return_value = main.Reply("Следующий трек.")
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response(raw)) as request:
            self.run_text(capri, "давай другую песню")
        self.assertEqual(request.call_count, 1)
        capri.actions.handle.assert_called_once()
        capri.actions.execute_decision.assert_called_once()

    def test_search_planning_without_api_keeps_fresh_facts_online(self):
        for text in ("Кто президент Франции?", "Курс доллара", "Посоветуй ноутбук", "Новости", "Погода в Томске"):
            self.assertEqual(economy_plan(text).route, "web")
        for text in ("Почему небо голубое?", "Объясни гравитацию", "Как устроен процессор?"):
            self.assertEqual(economy_plan(text).route, "local")

    def test_api_mode_never_constructs_local_model_or_warms_router(self):
        with patch("capri.app.controller.LocalAI") as local, patch("capri.app.controller.AI") as claude:
            capri = self.make_capri()
            capri._background = Mock()
            capri._start_models()
        local.assert_not_called()
        claude.assert_not_called()
        capri._background.assert_not_called()
        self.assertIsNone(capri.local)
        self.assertIsNotNone(capri.router.api_client)

    def test_switching_mode_cancels_work_and_updates_command_backend(self):
        capri = self.make_capri()
        capri.text_command("старый запрос")
        with patch("capri.app.controller._edit_config", return_value=None), patch("capri.app.controller.LocalAI") as local:
            capri.set_ai_settings("openai", "new-secret", "gpt-6-luna")
            local.assert_not_called()
        self.assertTrue(capri.jobs.empty())
        self.assertIs(capri.actions.ai, capri.ai)
        self.assertIsNone(capri.actions.local)
        self.assertEqual(capri.router.api_client.key, "new-secret")

    def test_settings_failure_does_not_switch_backend(self):
        capri = self.make_capri()
        previous = capri.ai
        with patch("capri.app.controller._edit_config", return_value="ошибка"), self.assertRaises(ValueError):
            capri.set_ai_settings("local", "", "")
        self.assertIs(capri.ai, previous)
        self.assertEqual(capri.cfg["ai_mode"], "openai")

    def test_dialog_masks_key_and_saves_mode(self):
        capri = Mock(cfg={"ai_mode": "openai", "openai_api_key": "secret"})
        dialog = AIDialog(capri)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.key.echoMode(), QLineEdit.EchoMode.Password)
        dialog.key.setText("updated-secret")
        dialog.save()
        capri.set_ai_settings.assert_called_once_with("openai", "updated-secret", "gpt-6-luna")

    def test_missing_key_stays_in_api_mode_without_local_fallback(self):
        capri = self.make_capri()
        capri.cfg["openai_api_key"] = ""
        capri.cfg.update(intent_router=False, local_ai=True)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("capri.app.controller._edit_config", return_value=None), \
                patch("capri.app.controller.LocalAI") as local:
            capri.set_ai_settings("openai", "", "gpt-6-luna")
        capri.actions.handle.return_value = None
        capri.actions.handle_conversation.return_value = None
        capri.actions.pending = capri.actions.choice = None
        capri.actions.normalize_voice_command.side_effect = lambda text: text
        capri.reload_config_if_changed = Mock()
        capri.say = Mock(return_value=False)
        capri.text_command("Объясни гравитацию")
        capri._process(capri.jobs.get_nowait())
        local.assert_not_called()
        self.assertIn("ключ", capri.say.call_args.args[0])
