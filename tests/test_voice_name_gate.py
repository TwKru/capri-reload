"""Only one command per explicit name; immediate wake without final recognition."""
import time
import unittest
from unittest.mock import Mock, patch

from capri.app import controller as main
from tests import test_listening


class VoiceNameGateTests(unittest.TestCase):
    def setUp(self):
        test_listening.ListeningTests.setUp(self)
        self.capri.cfg["voice_requires_name"] = True

    def voice_jobs(self):
        jobs = []
        while not self.capri.jobs.empty():
            job = self.capri.jobs.get_nowait()
            if job[0] == "voice":
                jobs.append(job)
        return jobs

    def test_default_requires_name_and_acknowledges(self):
        self.assertTrue(main.DEFAULTS["voice_requires_name"])
        self.assertTrue(main.DEFAULTS["speak_wake_ack"])
        self.assertNotIn("капли",main.DEFAULTS["wake_words"])

    def test_idle_and_old_listening_window_do_not_authorize_speech(self):
        self.capri.awake_until = time.time()+100
        self.capri.on_partial("открой блокнот")
        self.capri.on_final("открой блокнот",b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_response_question_requires_new_name_even_for_yes(self):
        pending = self.capri.actions.pending = Mock()
        self.capri.finish_reply("Подтверждаешь?",ask=True)
        self.capri.on_final("да",b"audio")
        self.assertTrue(self.capri.jobs.empty())
        self.assertIs(self.capri.actions.pending,pending)
        self.capri.on_final("капри да",b"audio")
        self.assertEqual(self.voice_jobs()[0][1],"да")

    def test_partial_name_responds_before_final_and_once(self):
        subtitles = []
        self.capri.subtitle.connect(subtitles.append)
        with patch.object(self.capri,"appear") as appear:
            self.capri.on_partial("капри")
            self.assertEqual(subtitles[-1],"Слушаю…")
            appear.assert_called_once()
            self.capri.on_partial("капри")
            self.capri.on_final("капри",b"name")
            appear.assert_called_once()
        self.assertEqual(self.capri.jobs.qsize(),1)
        self.assertEqual(self.capri.jobs.get_nowait()[0],"wake")

    def test_one_command_consumes_separate_name(self):
        self.capri.on_partial("капри")
        self.capri.on_final("капри",b"name")
        self.capri.on_final("открой блокнот",b"audio")
        self.capri.on_final("удали файл",b"other")
        self.assertEqual([job[1] for job in self.voice_jobs()],["открой блокнот"])

    def test_only_text_after_name_is_command(self):
        self.capri.on_final("открой браузер капри открой блокнот",b"audio")
        self.assertEqual(self.voice_jobs()[0][1],"открой блокнот")

    def test_address_expires_but_active_command_can_continue(self):
        with patch("capri.app.controller.time.time",return_value=100):
            self.capri.on_partial("капри")
        with patch("capri.app.controller.time.time",return_value=107):
            self.capri.on_partial("открой")
        with patch("capri.app.controller.time.time",return_value=113):
            self.capri.on_final("открой блокнот",b"audio")
        self.assertEqual(len(self.voice_jobs()),1)
        with patch("capri.app.controller.time.time",return_value=120):
            self.capri.on_partial("капри")
        with patch("capri.app.controller.time.time",return_value=140):
            self.capri.on_final("ещё команда",b"audio")
        self.assertFalse(self.voice_jobs())

    def test_unaddressed_stop_does_not_trigger_but_addressed_stop_does(self):
        self.capri.on_final("стоп",b"audio")
        self.capri.speaker.stop.assert_not_called()
        self.capri.on_partial("капри стоп")
        self.capri.speaker.stop.assert_called_once()
        self.assertEqual(self.capri.voice_wake_until,0)

    def test_name_cancels_active_work_before_queuing_ack(self):
        scope = self.capri._scope(lambda:False)
        self.capri.jobs.put(("text","old"))
        with patch.object(self.capri,"appear") as appear:
            self.capri.on_partial("капри")
        self.assertTrue(scope.event.is_set())
        appear.assert_called_once()
        self.assertEqual(self.capri.jobs.get_nowait()[0],"wake")
        self.assertTrue(self.capri.jobs.empty())

    def test_muted_and_echo_cannot_open_name_gate(self):
        self.capri.voice_paused = True
        self.capri.on_partial("капри")
        self.assertEqual(self.capri.voice_wake_until,0)
        self.capri.voice_paused = False
        self.capri.speaking = True
        self.capri.speech_words = {"капри","онлайн"}
        self.capri.on_partial("капри онлайн")
        self.assertEqual(self.capri.voice_wake_until,0)

    def test_speech_during_wake_ack_is_not_lost(self):
        self.capri.on_partial("капри")
        self.capri.acknowledging = self.capri.speaking = True
        self.capri.interrupted = False
        self.capri.speech_words = {"слушаю"}
        self.capri.on_partial("открой блокнот")
        self.capri.on_final("открой блокнот",b"audio")
        self.capri.speaker.stop.assert_called_once()
        self.assertEqual(self.voice_jobs()[0][1],"открой блокнот")

    def test_google_refinement_cannot_restore_text_before_name(self):
        self.capri.cfg["use_google_stt"] = True
        for refined in ("случайная речь капри открой блокнот", "случайная речь открой блокнот"):
            self.capri.actions.handle.reset_mock()
            self.capri._ask_ai = Mock(return_value=refined)
            self.capri.on_final("случайная речь капри открой блокнот",b"audio")
            self.capri._process(self.voice_jobs()[0])
            self.capri.actions.handle.assert_called_once_with("открой блокнот")
