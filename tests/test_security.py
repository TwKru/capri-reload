"""Регрессии: недоверенные ссылки, архивы, модель и сбои звукового устройства."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from actions import Actions
from intent_router import Decision
from tools import download_model
import updater
import voice


class SecurityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with patch("actions.AppIndex.build"):
            self.app = Actions({}, str(self.root), None)

    def test_browser_rejects_executable_schemes_and_control_characters(self):
        for url in ("javascript:alert(1)", "file:///C:/Windows/cmd.exe", "ms-msdt:/id", "--app=http://example.com",
                    "https://user:pass@example.com", "https://example.com\n--flag"):
            with self.subTest(url=url), patch("actions.subprocess.Popen") as start, \
                    patch("actions.webbrowser.open") as browser, self.assertRaises(ValueError):
                self.app.web(url)
            start.assert_not_called()
            browser.assert_not_called()

    def test_custom_app_fallback_never_uses_command_shell(self):
        with patch("actions.os.startfile", side_effect=OSError), patch("actions.subprocess.Popen") as start:
            self.app._run('program.exe & other.exe')
        self.assertFalse(start.call_args.kwargs["shell"])

    def test_ai_cannot_open_an_unmentioned_app(self):
        with patch.object(self.app, "open") as launch:
            self.app.execute_decision(Decision("open", "cmd"), original="Покажи телеграм")
        launch.assert_not_called()

    def test_missing_ai_mute_target_does_not_mute_all_windows_audio(self):
        with patch.object(self.app, "volume") as volume:
            self.app.execute_decision(Decision("mute"), original="выключи звук дискорда")
        self.assertEqual(volume.call_args.args[0], "выключи звук дискорда")

    def test_updater_rejects_windows_name_aliases_and_case_collisions(self):
        for name in (".git./config", "folder /file.py", "nul.txt", "COM1/data", "MAIN.py"):
            archive = self.root / "update.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("root/main.py", "pass")
                zipped.writestr("root/" + name, "pass")
            with self.subTest(name=name), self.assertRaises(ValueError):
                updater.extract(archive, self.root / "out")

    def test_pickle_model_checksum_is_checked_before_loading(self):
        path = self.root / "model.pt"
        path.write_bytes(b"untrusted pickle")
        with self.assertRaises(ValueError):
            voice.verify_silero(path)
        with patch("voice.SILERO_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()):
            voice.verify_silero(path)

    def test_vosk_bad_checksum_preserves_existing_model(self):
        target = self.root / download_model.NAME
        target.mkdir()
        (target / "personal").write_text("keep")
        archive = self.root / "bad.zip"
        archive.write_bytes(b"invalid")
        with patch.object(download_model, "MODELS", str(self.root)), \
                patch.object(download_model, "TARGET", str(target)), self.assertRaises(ValueError):
            download_model.unpack(archive)
        self.assertEqual((target / "personal").read_text(), "keep")

    def test_vosk_rejects_traversal_even_with_matching_checksum(self):
        for member in ("../outside.txt", download_model.NAME + "/../../outside.txt",
                       download_model.NAME + "/nul.txt"):
            archive = self.root / "model.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(member, "bad")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.subTest(member=member), patch.object(download_model, "MODELS", str(self.root)), \
                    patch.object(download_model, "TARGET", str(self.root / download_model.NAME)), \
                    patch.object(download_model, "MODEL_SHA256", digest), self.assertRaises(ValueError):
                download_model.unpack(archive)
        self.assertFalse((self.root.parent / "outside.txt").exists())


class VoiceReliabilityTests(unittest.TestCase):
    def test_play_failure_does_not_disable_online_synthesis(self):
        speaker = voice.Speaker({})
        with patch("voice.os.path.isfile", return_value=False), \
                patch.object(speaker, "_edge", side_effect=voice.VoicePlaybackError("device")), \
                patch.object(speaker, "_sapi", return_value=False) as fallback:
            speaker.say("Проверка")
        fallback.assert_called_once()
        self.assertEqual(speaker._edge_retry_at, 0)

    def test_play_command_error_is_not_reported_as_success(self):
        with patch("voice._mci", side_effect=[(0, ""), (0, ""), (1, ""), (0, "")]) as mci:
            with self.assertRaises(voice.VoicePlaybackError):
                voice.play_mp3("voice.wav", Mock())
        self.assertEqual(mci.call_args.args[0], "close capri_tts")

    def test_stale_prefetch_failure_does_not_disable_working_voice(self):
        speaker = voice.Speaker({})
        speaker._last_render_ok = 20
        speaker._edge_failed(TimeoutError(), started=10)
        self.assertIsNone(speaker.edge_error)
        self.assertEqual(speaker._edge_retry_at, 0)

    def test_voice_service_backoff_is_capped_at_a_minute(self):
        speaker = voice.Speaker({})
        with patch("voice.time.monotonic", return_value=100):
            for _ in range(6):
                speaker._edge_failed(TimeoutError())
                self.assertLessEqual(speaker._edge_retry_at, 160)


if __name__ == "__main__":
    unittest.main()
