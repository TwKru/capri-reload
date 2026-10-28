"""Паузы между фрагментами Vosk без реального микрофона."""
import json
import queue
import unittest
from unittest.mock import patch

from voice import Listener


class PhraseEndpointTests(unittest.TestCase):
    def run_audio(self, steps, stop_on_partial=False):
        results = []
        clock = [0.0]
        current = [None]
        partials = []

        def partial(text):
            partials.append(text)
            if stop_on_partial and text == "стоп":
                listener.reset_req.set()

        listener = Listener("unused", lambda text, audio: results.append((text, audio)),
                            partial, lambda *args: None)

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        class AudioQueue:
            def get(self, timeout):
                if not steps:
                    listener.switch.set()
                    raise queue.Empty
                current[0] = steps.pop(0)
                clock[0] = current[0][0]
                listener.level = current[0][3]
                return b"\0\0" * 4000

        class Recognizer:
            def AcceptWaveform(self, data):
                return current[0][1]

            def Result(self):
                return json.dumps({"text": current[0][2]})

            def PartialResult(self):
                return json.dumps({"partial": current[0][2]})

            def Reset(self):
                pass

        with patch.object(listener, "process", side_effect=lambda data: data), \
                patch("voice.time.monotonic", side_effect=lambda: clock[0]):
            listener._listen(Stream(), AudioQueue(), Recognizer())
        return results, partials

    def test_pause_in_middle_is_joined_into_one_command(self):
        results, _ = self.run_audio([
            (0.0, True, "капри открой", 0),
            (0.3, False, "", 0),
            (0.7, False, "ютуб", 0.2),
            (1.4, False, "ютуб и найди музыку", 0.2),
            (2.0, True, "ютуб и найди музыку", 0),
            (2.5, False, "", 0),
            (3.0, False, "", 0),
        ])
        self.assertEqual([text for text, _ in results], ["капри открой ютуб и найди музыку"])
        self.assertEqual(len(results[0][1]), 7 * 8000)

    def test_started_continuation_is_not_cut_by_old_deadline(self):
        results, _ = self.run_audio([
            (0.0, True, "капри", 0),
            (0.4, False, "расскажи", 0.1),
            (1.5, False, "расскажи", 0),
            (2.5, False, "расскажи про космос", 0.1),
            (3.0, True, "расскажи про космос", 0),
            (4.0, False, "", 0),
        ])
        self.assertEqual([text for text, _ in results], ["капри расскажи про космос"])

    def test_separate_phrases_are_not_merged_after_full_pause(self):
        results, _ = self.run_audio([
            (0.0, True, "капри открой ютуб", 0),
            (1.0, False, "", 0),
            (2.0, False, "случайный разговор", 0.1),
            (3.0, True, "случайный разговор", 0),
            (4.0, False, "", 0),
        ])
        self.assertEqual([text for text, _ in results], ["капри открой ютуб", "случайный разговор"])

    def test_stop_cancels_pending_phrase_without_waiting(self):
        results, partials = self.run_audio([
            (0.0, True, "капри открой", 0),
            (0.5, False, "стоп", 0),
            (0.8, False, "", 0),
            (2.0, False, "", 0),
        ], stop_on_partial=True)
        self.assertIn("стоп", partials)
        self.assertEqual(results, [])

    def test_stop_without_partial_result_is_also_immediate(self):
        results, partials = self.run_audio([
            (0.0, True, "капри открой", 0),
            (0.5, True, "стоп", 0),
            (1.0, False, "", 0),
            (2.0, False, "", 0),
        ], stop_on_partial=True)
        self.assertIn("стоп", partials)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
