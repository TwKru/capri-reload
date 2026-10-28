"""Проверки без сети, микрофона, ввода в окна и изменения громкости Windows."""
import asyncio
import pathlib
import re
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

import actions
import automation
import voice
from local_ai import LocalAI


class CommandTests(unittest.TestCase):
    def setUp(self):
        with patch.object(actions.AppIndex, "build"):
            self.app = actions.Actions({}, ".", None)

    def test_fast_command_detection_does_not_execute_actions(self):
        self.app.sites = {"ютуб": "https://www.youtube.com"}
        for command in ("открой ютуб", "выключи звук браузера", "громкость браузера ноль", "поставь на паузу"):
            with self.subTest(command=command):
                self.assertTrue(self.app.is_fast_command(command))
        for command in ("найди музыку", "открой неизвестный сайт", "выключи компьютер",
                        "напиши привет", "почему звук браузера тихий", "как увеличить громкость"):
            with self.subTest(command=command):
                self.assertFalse(self.app.is_fast_command(command))


    def test_diagnostics_require_a_command(self):
        for command in ("ты умеешь анализировать файлы на моём компьютере",
                        "как проверить компьютер", "расскажи про диагностику пк"):
            with self.subTest(command=command):
                with patch.object(actions, "analyze_pc") as scan:
                    self.app.handle(command)
                    scan.assert_not_called()
        for command in ("проверь компьютер", "пожалуйста проверь мой компьютер",
                        "проанализируй систему", "сделай диагностику компьютера", "диагностика пк"):
            with self.subTest(command=command):
                matching = [fn for pattern, fn in self.app.routes
                            if re.search(pattern, command)]
                self.assertIn(self.app.analyze, matching)

    def test_browser_volume_does_not_change_system_or_other_apps(self):
        chrome, firefox, player = Mock(), Mock(), Mock()
        for volume in (chrome, firefox, player):
            volume.GetMasterVolume.return_value = 0.7
        sessions = [types.SimpleNamespace(Process=types.SimpleNamespace(name=lambda name=name: name),
                                          SimpleAudioVolume=volume)
                    for name, volume in (("chrome.exe", chrome), ("firefox.exe", firefox),
                                         ("player.exe", player))]
        with patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=sessions), \
                patch.object(actions, "_endpoint") as endpoint:
            self.app.handle("сделай громкость браузера ноль")
            chrome.SetMasterVolume.assert_called_once_with(0, None)
            firefox.SetMasterVolume.assert_called_once_with(0, None)
            player.SetMasterVolume.assert_not_called()
            endpoint.assert_not_called()
            chrome.reset_mock()
            firefox.reset_mock()
            self.app.handle("сделай громкость хрома 40")
            chrome.SetMasterVolume.assert_called_once_with(0.4, None)
            firefox.SetMasterVolume.assert_not_called()
            chrome.reset_mock()
            self.app.handle("громкость 40 в хроме")
            chrome.SetMasterVolume.assert_called_once_with(0.4, None)
            endpoint.assert_not_called()
            self.app.handle("выключи звук в хроме")
            chrome.SetMute.assert_called_with(True, None)
            endpoint.assert_not_called()

    def test_missing_browser_session_does_not_change_system(self):
        with patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[]), \
                patch.object(actions, "_endpoint") as endpoint:
            reply = self.app.handle("сделай громкость браузера ноль")
            self.assertIn("сессию", reply.text)
            endpoint.assert_not_called()

    def test_zen_browser_audio_session(self):
        volume = Mock()
        volume.GetMasterVolume.return_value = 0.7
        session = types.SimpleNamespace(Process=types.SimpleNamespace(name=lambda: "zen.exe"),
                                        SimpleAudioVolume=volume)
        with patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[session]), \
                patch.object(actions, "_endpoint") as endpoint:
            for command in ("выключи звук браузера", "выключи звук в зене", "выключи звук zen"):
                with self.subTest(command=command):
                    volume.reset_mock()
                    reply = self.app.handle(command)
                    volume.SetMute.assert_called_once_with(True, None)
                    self.assertNotIn("Не нашла", reply.text)
            volume.reset_mock()
            self.app.handle("громкость 40 в зене")
            volume.SetMasterVolume.assert_called_once_with(0.4, None)
            volume.reset_mock()
            self.app.handle("громкость хрома 40")
            volume.SetMasterVolume.assert_not_called()
            endpoint.assert_not_called()

    def test_system_volume_still_works(self):
        with patch.object(actions, "get_volume", return_value=70), \
                patch.object(actions, "set_volume") as write:
            self.app.handle("сделай громкость 40")
            write.assert_called_once_with(40)


class LocalPerformanceTests(unittest.TestCase):
    def test_keep_alive_applies_to_warmup_and_chat(self):
        for cfg, expected in (({}, "30m"), ({"local_keep_alive": "15m"}, "15m")):
            with self.subTest(cfg=cfg):
                ai = LocalAI(cfg)
                with patch.object(ai, "installed", return_value=[ai.model]), \
                        patch("local_ai._post", return_value={"message": {"content": "Готово."}}) as post:
                    ai.start_server()
                    self.assertEqual(post.call_args.args[1]["keep_alive"], expected)
                    ai._chat([{"role": "user", "content": "Привет"}])
                    self.assertEqual(post.call_args.args[1]["keep_alive"], expected)

    def test_local_chat_timeout_is_short_and_configurable(self):
        for cfg, expected in (({}, 15), ({"local_timeout_seconds": 5}, 5)):
            with patch("local_ai._post", return_value={"message": {"content": "Готово."}}) as post:
                LocalAI(cfg)._chat([{"role": "user", "content": "Привет"}])
                self.assertEqual(post.call_args.args[2], expected)


class UnicodeTests(unittest.TestCase):
    def test_send_input_uses_utf16_units(self):
        captured = []

        def send(count, inputs, size):
            captured.extend((inputs[i].u.ki.wScan, inputs[i].u.ki.dwFlags) for i in range(count))
            return count

        with patch.object(automation, "u", types.SimpleNamespace(SendInput=send)):
            automation.type_text("Я😀\n", delay=0)
        units = [0x42F, 0xD83D, 0xDE00, 0x0D]
        expected = [(unit, flag) for unit in units for flag in (4, 6)]
        self.assertEqual(captured, expected)


class SpeechTests(unittest.TestCase):
    def test_prewarm_and_speech_use_separate_files_and_cleanup(self):
        barrier = threading.Barrier(2)
        source_paths, played, errors = [], [], []

        class Communicate:
            def __init__(self, text, *args, **kwargs):
                self.text = text

            async def save(self, path):
                source_paths.append(path)
                pathlib.Path(path).write_text(self.text, encoding="utf-8")
                await asyncio.to_thread(barrier.wait, 5)

        def decode(path):
            value = 1 if pathlib.Path(path).read_text(encoding="utf-8") == "speech" else 2
            return np.full(100, value, dtype=np.float32)

        def write(path, data, **kwargs):
            pathlib.Path(path).write_text(str(int(data[0])), encoding="utf-8")

        def play(path, *args):
            played.append(pathlib.Path(path).read_text(encoding="utf-8"))
            return False

        def run(fn):
            try:
                fn()
            except Exception as error:
                errors.append(error)

        speaker = voice.Speaker({"voice_fx": 0, "voice_lively": False, "voice_shift": 0})
        with tempfile.TemporaryDirectory() as cache, \
                patch.object(voice, "TTS_CACHE", cache), \
                patch.dict("sys.modules", {"edge_tts": types.SimpleNamespace(Communicate=Communicate)}), \
                patch.object(voice, "decode", decode), patch.object(voice, "write_wav", write), \
                patch.object(voice, "play_mp3", play):
            workers = [threading.Thread(target=run, args=(lambda: speaker._edge("speech"),)),
                       threading.Thread(target=run, args=(lambda: speaker.prewarm(["prewarm"]),))]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(10)
                self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(played, ["1"])
            self.assertEqual(len(set(source_paths)), 2)
            self.assertEqual(pathlib.Path(speaker._cache_path("speech")).read_text(), "1")
            self.assertEqual(pathlib.Path(speaker._cache_path("prewarm")).read_text(), "2")
        self.assertTrue(all(not pathlib.Path(path).exists() for path in source_paths))

    def test_mp3_fallback_is_kept_until_playback_then_removed(self):
        seen = []

        class Communicate:
            def __init__(self, *args, **kwargs):
                pass

            async def save(self, path):
                pathlib.Path(path).write_bytes(b"mp3")

        def play(path, *args):
            self.assertEqual(pathlib.Path(path).read_bytes(), b"mp3")
            seen.append(path)
            return True

        speaker = voice.Speaker({})
        with tempfile.TemporaryDirectory() as cache, patch.object(voice, "TTS_CACHE", cache), \
                patch.dict("sys.modules", {"edge_tts": types.SimpleNamespace(Communicate=Communicate)}), \
                patch.object(voice, "decode", side_effect=RuntimeError("decode failed")), \
                patch.object(voice, "play_mp3", play), patch.object(voice.log, "exception"):
            self.assertTrue(speaker._edge("one sentence"))
            self.assertTrue(speaker._edge("First. Second."))
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(not pathlib.Path(path).exists() for path in seen))


if __name__ == "__main__":
    unittest.main()
