"""Gemini: протокол AI Studio, экономия, память и переключение без Ollama."""
import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLineEdit

from capri.ai.intent_router import COMMAND_SCHEMA, IntentRouter
from capri.ai.providers.gemini_provider import (
    DEFAULT_GEMINI_MODEL,
    Gemini,
    GeminiClient,
)
from capri.ai.providers.openai_provider import APIError
from capri.app import controller as main
from capri.core import cancellation
from capri.storage.conversation_memory import MemoryStore
from capri.ui.dialogs.ai_settings import AIDialog


def response(text="Ответ.", reason="STOP", thought=False):
    parts = [{"text": "Скрытые рассуждения", "thought": True}] if thought else []
    parts.append({"text": text})
    return io.BytesIO(json.dumps({"candidates": [{"content": {"role": "model", "parts": parts},
        "finishReason": reason}], "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 5,
        "thoughtsTokenCount": 0}}).encode())


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"ai_mode": "gemini", "gemini_api_key": "fake-google-key"}

    def test_native_google_endpoint_and_header_roles_and_token_budget(self):
        client = GeminiClient(self.cfg)
        messages = [{"role": "system", "content": "Инструкция"}, {"role": "user", "content": "Привет"},
                    {"role": "assistant", "content": "Привет!"}, {"role": "user", "content": "Вопрос"}]
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response(thought=True)) as request:
            self.assertEqual(client.complete(messages, tokens=160), "Ответ.")
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_GEMINI_MODEL}:generateContent")
        self.assertNotIn("fake-google-key", sent.full_url)
        self.assertEqual(sent.get_header("X-goog-api-key"), "fake-google-key")
        body = json.loads(sent.data)
        self.assertNotIn("fake-google-key", sent.data.decode())
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Инструкция")
        self.assertEqual([item["role"] for item in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "MINIMAL"})
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 416)

    def test_router_uses_google_json_schema_and_keeps_question_guard(self):
        router = IntentRouter(self.cfg)
        decision = {"action": "music", "target": "", "value": None, "relative": False}
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response(json.dumps(decision))) as request:
            self.assertEqual(router.ask("Как выключить компьютер?").action, "chat")
        config = json.loads(request.call_args.args[0].data)["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseJsonSchema"], COMMAND_SCHEMA)
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            router.warmup()
            request.assert_not_called()

    def test_legacy_flash_disables_thinking_and_pro_keeps_supported_budget(self):
        for model, budget in (("gemini-2.5-flash", 0), ("gemini-2.5-pro", 128)):
            client = GeminiClient(dict(self.cfg, gemini_model=model))
            config = client._generation_config(160, None)
            self.assertEqual(config["thinkingConfig"], {"thinkingBudget": budget})
            self.assertEqual(config["maxOutputTokens"], 160 + budget)

    def test_environment_keys_and_model_resource_prefix(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "from-env", "GOOGLE_API_KEY": "other"}):
            client = GeminiClient({"gemini_model": "models/" + DEFAULT_GEMINI_MODEL})
            self.assertEqual(client.key, "from-env")
            self.assertEqual(client.model, DEFAULT_GEMINI_MODEL)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "google-env"}):
            self.assertEqual(GeminiClient({}).key, "google-env")

    def test_missing_key_and_bad_model_do_not_make_network_requests(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            ai = Gemini({})
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            self.assertIn("ключ Google", ai.ask("Вопрос"))
            client = GeminiClient(dict(self.cfg, gemini_model="https://another-server/"))
            with self.assertRaises(APIError):
                client.complete([{"role": "user", "content": "Вопрос"}])
            request.assert_not_called()

    def test_http_errors_do_not_leak_secret_or_enter_history(self):
        ai = Gemini(self.cfg)
        for status in (400, 401, 403, 404, 429, 500):
            error = urllib.error.HTTPError("https://generativelanguage.googleapis.com", status,
                "fake-google-key", {}, io.BytesIO(b"fake-google-key"))
            with patch("capri.core.cancellation.urllib.request.urlopen", side_effect=error):
                text = ai.ask("Вопрос")
            self.assertNotIn("fake-google-key", text)
            self.assertEqual(ai.history, [])
            self.assertFalse(ai.last_request_succeeded)

    def test_blocked_and_empty_responses_do_not_enter_history(self):
        for body in (json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode(),
                     response("", "STOP").getvalue(), response("Ответ", "SAFETY").getvalue()):
            ai = Gemini(self.cfg)
            with patch("capri.core.cancellation.urllib.request.urlopen", return_value=io.BytesIO(body)):
                ai.ask("Вопрос")
            self.assertEqual(ai.history, [])

    def test_http_400_distinguishes_region_from_invalid_key_without_echoing_secrets(self):
        for message, reason, expected in (
            ("User location is not supported for the API use.", "", "регионе"),
            ("API key not valid. fake-google-key", "API_KEY_INVALID", "API-ключ"),
            ("Gemini API free tier is not available in your country.", "", "Бесплатный"),
            ("Your API key was reported as leaked. fake-google-key", "", "скомпрометированный"),
        ):
            ai = Gemini(self.cfg)
            body = {"error":{"message":message,"details":[{"reason":reason}]}}
            error = urllib.error.HTTPError("https://generativelanguage.googleapis.com",400,"Bad Request",{},
                                           io.BytesIO(json.dumps(body).encode()))
            with patch("capri.core.cancellation.urllib.request.urlopen",side_effect=error):
                text = ai.ask("Question")
            self.assertIn(expected,text)
            self.assertNotIn("fake-google-key",text)
            self.assertEqual(ai.history,[])

    def test_limited_output_does_not_retry_or_return_broken_json(self):
        client = GeminiClient(self.cfg)
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response("Ответ. Оборванная фраза", "MAX_TOKENS")) as request:
            self.assertEqual(client.complete([{"role": "user", "content": "Вопрос"}]), "Ответ.")
        request.assert_called_once()
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response('{"action":', "MAX_TOKENS")), self.assertRaises(APIError):
            client.complete([{"role": "user", "content": "Вопрос"}], schema=COMMAND_SCHEMA)

    def test_cancelled_response_does_not_commit_history(self):
        ai = Gemini(self.cfg)
        scope = cancellation.Scope()
        def cancel(*args, **kwargs):
            scope.cancel()
            return response()
        with scope.bind(), patch("capri.core.cancellation.urllib.request.urlopen", side_effect=cancel), self.assertRaises(cancellation.RequestCancelled):
            ai.ask("Вопрос")
        self.assertEqual(ai.history, [])


class GeminiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.cfg = copy.deepcopy(main.DEFAULTS)
        self.cfg.update(ai_mode="gemini", gemini_api_key="fake-google-key", openai_api_key="fake-openai-key")
        sound = patch("capri.app.controller.stop_sound")
        sound.start()
        self.addCleanup(sound.stop)

    def make_capri(self):
        with patch("capri.app.controller.Actions"), patch("capri.app.controller.Speaker"), patch("capri.app.controller.make_glitch_sound"):
            return main.Capri(copy.deepcopy(self.cfg))

    def test_gemini_mode_does_not_create_or_warm_local_models(self):
        with patch("capri.app.controller.LocalAI") as local, patch("capri.app.controller.AI") as claude, patch("capri.app.controller.OpenAI") as openai:
            capri = self.make_capri()
            capri._background = Mock()
            capri._start_models()
        self.assertIsInstance(capri.ai, Gemini)
        self.assertIsInstance(capri.router.api_client, GeminiClient)
        self.assertIsNone(capri.local)
        local.assert_not_called()
        claude.assert_not_called()
        openai.assert_not_called()
        capri._background.assert_not_called()

    def test_clear_question_uses_one_google_request_and_no_other_provider(self):
        capri = self.make_capri()
        capri.actions.pending = capri.actions.choice = None
        capri.actions.handle_conversation.return_value = None
        capri.reload_config_if_changed = Mock()
        capri.say = Mock(return_value=False)
        with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response()) as request:
            capri.text_command("Почему небо голубое?")
            capri._process(capri.jobs.get_nowait())
        self.assertEqual(request.call_count, 1)
        self.assertIn("generativelanguage.googleapis.com", request.call_args.args[0].full_url)
        capri.actions.handle.assert_not_called()

    def test_missing_key_does_not_start_local_fallback(self):
        self.cfg["gemini_api_key"] = ""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}), patch("capri.app.controller.LocalAI") as local:
            capri = self.make_capri()
            capri._start_models()
            local.assert_not_called()
        capri.actions.pending = capri.actions.choice = None
        capri.actions.handle_conversation.return_value = None
        capri.reload_config_if_changed = Mock()
        capri.say = Mock(return_value=False)
        with patch("capri.core.cancellation.urllib.request.urlopen") as request:
            capri.text_command("Объясни гравитацию")
            capri._process(capri.jobs.get_nowait())
            request.assert_not_called()
        self.assertIn("ключ Google", capri.say.call_args.args[0])
        self.assertIsNone(capri.local)

    def test_switching_providers_preserves_other_key_and_restores_memory(self):
        capri = self.make_capri()
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = Path(directory) / "config.json"
            cfg_path.write_text(json.dumps(self.cfg), encoding="utf-8")
            memory_path = Path(directory) / "memory.json"
            capri.enable_memory(memory_path)
            capri.memory.record("Вопрос", "Ответ.")
            with patch("capri.config.settings.CONFIG_PATH", str(cfg_path)), patch("capri.app.controller.LocalAI") as local:
                capri.set_ai_settings("gemini", "new-google-key", DEFAULT_GEMINI_MODEL)
                self.assertEqual(capri.cfg["openai_api_key"], "fake-openai-key")
                self.assertEqual(capri.ai.history[-1]["content"], "Ответ.")
                capri.set_ai_settings("openai", "new-openai-key", "gpt-6-luna")
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["gemini_api_key"], "new-google-key")
                self.assertEqual(data["openai_api_key"], "new-openai-key")
                local.assert_not_called()

    def test_gemini_answers_use_and_save_file_memory(self):
        capri = self.make_capri()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            capri.enable_memory(path)
            capri.memory.remember("моего кота зовут Барсик")
            with patch("capri.core.cancellation.urllib.request.urlopen", return_value=response("Твоего кота зовут Барсик.")) as request:
                capri._ask_ai(capri.ai, "Как зовут моего кота?", lambda: False)
            body = json.loads(request.call_args.args[0].data)
            self.assertIn("Барсик", body["systemInstruction"]["parts"][0]["text"])
            self.assertIn("Барсик", MemoryStore(path).recent()[-1]["content"])

    def test_ui_retains_provider_drafts_masks_key_and_saves_selected_provider(self):
        capri = Mock(cfg=self.cfg)
        dialog = AIDialog(capri)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.mode.currentData(), "gemini")
        self.assertTrue(dialog.key.isHidden())
        self.assertEqual(dialog.gemini_key.echoMode(), QLineEdit.EchoMode.Password)
        dialog.gemini_key.setText("updated-google")
        dialog.mode.setCurrentIndex(dialog.mode.findData("openai"))
        self.assertEqual(dialog.key.text(), "fake-openai-key")
        dialog.mode.setCurrentIndex(dialog.mode.findData("gemini"))
        self.assertEqual(dialog.gemini_key.text(), "updated-google")
        dialog.save()
        capri.set_ai_settings.assert_called_once_with("gemini", "updated-google", DEFAULT_GEMINI_MODEL)
