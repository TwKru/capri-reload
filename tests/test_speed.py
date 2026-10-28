"""Потоковые ответы и быстрый запасной голос без сети и воспроизведения звука."""
import json
import asyncio
import unittest
from unittest.mock import patch

import local_ai
import voice
from actions import Actions


class Response:
    def __init__(self, packets):
        self.packets = packets

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        for packet in self.packets:
            yield json.dumps(packet).encode("utf-8") + b"\n"


class StreamingTests(unittest.TestCase):
    def test_sentences_arrive_before_done_and_history_is_complete(self):
        spoken = []
        def packets():
            yield {"message": {"content": "Привет. Вторая"}}
            self.assertEqual(spoken, ["Привет."])
            yield {"message": {"content": " фраза."}, "done": True}
        ai = local_ai.LocalAI({})
        with patch("local_ai.urllib.request.urlopen", return_value=Response(packets())) as request:
            answer = ai.ask("Поговорим?", on_sentence=spoken.append)
        self.assertEqual(spoken, ["Привет.", "Вторая фраза."])
        self.assertEqual(answer, "Привет. Вторая фраза.")
        self.assertEqual(ai.history[-1]["content"], answer)
        payload = json.loads(request.call_args.args[0].data)
        self.assertTrue(payload["stream"])
        self.assertFalse(payload["think"])

    def test_thinking_and_search_mark_are_not_spoken(self):
        for content, expected in (("<think>Секретные мысли.</think>Привет.", ["Привет."]),
                                  ("ПОИСК", [])):
            with self.subTest(content=content):
                spoken = []
                with patch("local_ai.urllib.request.urlopen", return_value=Response([
                        {"message": {"content": content}, "done": True}])):
                    local_ai.LocalAI({}).ask("Поговорим?", on_sentence=spoken.append)
                self.assertEqual(spoken, expected)

    def test_connection_error_does_not_repeat_already_spoken_sentence(self):
        spoken = []
        def packets():
            yield {"message": {"content": "Привет. Незаконченный"}}
            raise OSError("Connection lost")
        with patch("local_ai.urllib.request.urlopen", return_value=Response(packets())):
            answer = local_ai.LocalAI({}).ask("Поговорим?", on_sentence=spoken.append)
        self.assertEqual(spoken, ["Привет."])
        self.assertEqual(answer, "Привет.")


class VoiceSpeedTests(unittest.TestCase):
    def test_failed_service_is_not_retried_on_every_phrase(self):
        speaker = voice.Speaker({})
        clock = [0]
        with patch.object(speaker, "_edge", side_effect=[RuntimeError("No audio"), False]) as edge, \
                patch.object(speaker, "_sapi", return_value=False) as sapi, \
                patch("voice.os.path.isfile", return_value=False), \
                patch("voice.time.monotonic", side_effect=lambda: clock[0]):
            speaker.say("Первая фраза.")
            clock[0] = 1
            speaker.say("Вторая фраза.")
            self.assertEqual(edge.call_count, 1)
            self.assertEqual(sapi.call_count, 2)
            clock[0] = 61
            speaker.say("Третья фраза.")
            self.assertEqual(edge.call_count, 2)
            self.assertIsNone(speaker.edge_error)

    def test_cached_voice_is_used_even_during_service_outage(self):
        speaker = voice.Speaker({})
        speaker._edge_retry_at = float("inf")
        with patch("voice.os.path.isfile", return_value=True), \
                patch.object(speaker, "_edge", return_value=False) as edge, \
                patch.object(speaker, "_sapi") as sapi:
            speaker.say("Готовая фраза.")
        edge.assert_called_once()
        sapi.assert_not_called()

    def test_stop_during_synthesis_does_not_start_fallback_speech(self):
        speaker = voice.Speaker({})
        def fail(text):
            speaker.stop()
            raise RuntimeError("No audio")
        with patch("voice.os.path.isfile", return_value=False), \
                patch.object(speaker, "_edge", side_effect=fail), patch.object(speaker, "_sapi") as sapi:
            self.assertTrue(speaker.say("Перебитая фраза."))
        sapi.assert_not_called()

    def test_synthesis_has_a_timeout(self):
        speaker = voice.Speaker({})
        speaker.tts_timeout = 0.01
        class Communicate:
            def __init__(self, *args, **kwargs):
                pass
            async def save(self, path):
                await asyncio.sleep(1)
        with patch("edge_tts.Communicate", Communicate), self.assertRaises(TimeoutError):
            speaker.render("Проверка.", "unused.wav")


class FastShuffleTests(unittest.TestCase):
    def test_natural_shuffle_commands_do_not_need_ai_or_google(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        for command in ("shuffle", "перемешай мои песни", "перемешай музыку", "шаффл"):
            with self.subTest(command=command), patch.object(app, "_set_playback_mode", return_value=True) as mode:
                app.handle(command)
                mode.assert_called_once_with("shuffle", True)
                self.assertTrue(app.is_fast_command(command))


if __name__ == "__main__":
    unittest.main()
