"""Failure isolation and cancellation of the native Windows speech worker."""
import json
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

import voice


class WindowsVoiceTests(unittest.TestCase):
    def process(self):
        return Mock(returncode=0, **{"poll.return_value": 0, "communicate.return_value": (None, b"")})

    def test_text_is_data_and_command_is_constant(self):
        process = self.process()
        text = "$(malicious); <speak>plain text</speak>"
        with patch("voice.subprocess.Popen", return_value=process) as launch:
            self.assertFalse(voice.render_windows_voice(text, "voice.wav", threading.Event()))
        args = launch.call_args.args[0]
        self.assertEqual(args[-1], voice.WINDOWS_TTS_SCRIPT)
        self.assertNotIn(text, args[-1])
        self.assertEqual(json.loads(process.communicate.call_args.kwargs["input"])["text"], text)
        self.assertEqual(launch.call_args.kwargs["creationflags"], 0x08000000)

    def test_pre_cancelled_does_not_start_worker(self):
        stop = threading.Event()
        stop.set()
        with patch("voice.subprocess.Popen") as launch:
            self.assertTrue(voice.render_windows_voice("hello", "voice.wav", stop))
        launch.assert_not_called()

    def test_stop_kills_and_reaps_worker(self):
        stop = threading.Event()
        process = self.process()
        process.poll.return_value = None
        def communicate(**kwargs):
            if "input" in kwargs:
                stop.set()
                raise subprocess.TimeoutExpired("speech", 0.1)
            return None, b""
        process.communicate.side_effect = communicate
        with patch("voice.subprocess.Popen", return_value=process):
            self.assertTrue(voice.render_windows_voice("hello", "voice.wav", stop))
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_worker_failure_is_a_python_exception(self):
        process = self.process()
        process.returncode = -1073741819
        with patch("voice.subprocess.Popen", return_value=process), self.assertRaises(RuntimeError):
            voice.render_windows_voice("hello", "voice.wav", threading.Event())

    def test_hung_worker_is_killed(self):
        process = self.process()
        process.poll.return_value = None
        with patch("voice.subprocess.Popen", return_value=process), self.assertRaises(TimeoutError):
            voice.render_windows_voice("hello", "voice.wav", threading.Event(), timeout=-1)
        process.kill.assert_called_once()
        process.communicate.assert_called_once_with()
