import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from capri.app.setup_service import api_settings, local_settings, save_setup
from capri.config.defaults import DEFAULTS
from capri.core import cancellation
from capri.ui.setup_wizard import SetupWizard


class SetupServiceTests(unittest.TestCase):
    def test_api_mode_never_enables_local_router(self):
        settings = api_settings("openai", " test-key ", " test-model ")
        self.assertFalse(settings["local_ai"])
        self.assertFalse(settings["intent_router"])
        self.assertEqual(settings["openai_api_key"], "test-key")
        with self.assertRaises(ValueError):
            api_settings("openai", "", "model")

    def test_existing_keys_voice_and_memory_options_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps({"gemini_api_key": "existing", "voice_volume": 17,
                                        "voice_shift": 1.7, "remember": True}), encoding="utf-8")
            save_setup(path, api_settings("openai", "new-key", "model"))
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["gemini_api_key"], "existing")
            self.assertEqual(result["voice_volume"], 17)
            self.assertEqual(result["voice_shift"], 1.7)
            self.assertTrue(result["setup_complete"])
            self.assertFalse(result["setup_pending"])

    def test_corrupt_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_setup(path, api_settings("openai", "key", "model"))
            self.assertEqual(path.read_text(), "{broken")

    def test_missing_model_cannot_be_activated(self):
        with self.assertRaises(ValueError):
            local_settings({})


class SetupWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_api_key_is_masked_and_saved_only_after_submit(self):
        with tempfile.TemporaryDirectory() as temp:
            wizard = SetupWizard(DEFAULTS, base=temp, initial_mode="api")
            self.assertEqual(wizard.pages.currentIndex(), 1)
            self.assertEqual(wizard.key.echoMode(), QLineEdit.EchoMode.Password)
            wizard.advance()
            self.assertEqual(wizard.pages.currentIndex(), 1)
            self.assertFalse((Path(temp) / "config.json").exists())
            wizard.key.setText("test-key")
            wizard.advance()
            self.assertEqual(wizard.pages.currentIndex(), 2)
            cfg = json.loads((Path(temp) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["tts_engine"], "silero")
            self.assertEqual(cfg["ai_mode"], "openai")
            wizard.close()

    def test_local_worker_reports_completion_without_network_or_console(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model, server = root / "model.gguf", root / "llama-server.exe"
            model.write_bytes(b"model")
            server.write_bytes(b"server")
            files = {"llama_executable": str(server), "llama_model": str(model)}
            wizard = SetupWizard(DEFAULTS, base=root, initial_mode="local")
            with patch("capri.ui.setup_wizard.install", return_value=files):
                wizard.advance()
                deadline = time.monotonic() + 5
                while wizard.worker and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertIsNone(wizard.worker)
            self.assertEqual(wizard.pages.currentIndex(), 2)
            cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["ai_mode"], "llamacpp")
            self.assertEqual(cfg["llama_model"], str(model))
            wizard.close()

    def test_cancel_before_confirmation_does_not_save(self):
        with tempfile.TemporaryDirectory() as temp:
            wizard = SetupWizard(DEFAULTS, base=temp)
            wizard.reject()
            self.assertFalse((Path(temp) / "config.json").exists())

    def test_download_failure_keeps_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            original = '{"openai_api_key":"keep-me","ai_mode":"openai"}'
            path.write_text(original, encoding="utf-8")
            wizard = SetupWizard(DEFAULTS, base=temp, initial_mode="local")
            with patch("capri.ui.setup_wizard.install", side_effect=OSError("offline")):
                wizard.advance()
                deadline = time.monotonic() + 5
                while wizard.worker and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(wizard.worker)
            self.assertEqual(path.read_text(), original)
            self.assertTrue(wizard.error.text())
            wizard.close()

    def test_cancelling_active_download_does_not_activate_or_save(self):
        def download(*args, **kwargs):
            for _ in range(200):
                cancellation.checkpoint()
                time.sleep(.005)
            raise RuntimeError("Cancellation was not observed")

        with tempfile.TemporaryDirectory() as temp:
            wizard = SetupWizard(DEFAULTS, base=temp, initial_mode="local")
            with patch("capri.ui.setup_wizard.install", side_effect=download):
                wizard.advance()
                wizard.reject()
                deadline = time.monotonic() + 5
                while wizard.worker and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(wizard.worker)
            self.assertFalse((Path(temp) / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
