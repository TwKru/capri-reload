"""Сценарии обращения по имени и остановки без микрофона, сети и интерфейса."""
import copy
import time
import threading
import unittest
from unittest.mock import Mock, patch

import main
from actions import Reply
from intent_router import Decision


class ListeningTests(unittest.TestCase):
    def setUp(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, use_google_stt=False, intent_router=False)
        with patch.object(main, "Actions"), patch.object(main, "Speaker"), \
                patch.object(main, "AI"), patch.object(main, "make_glitch_sound"):
            self.capri = main.Capri(cfg)
        self.capri.reload_config_if_changed = Mock()
        self.capri.actions.handle.return_value = Reply("Готово.")
        self.capri.actions.is_fast_command.return_value = False
        self.capri.actions.normalize_voice_command.side_effect = lambda cmd: cmd
        self.capri.actions.stop_background.return_value = False
        self.capri._check_voice_blocked = Mock()
        self.modes = []
        self.capri.mode.connect(lambda mode, seconds: self.modes.append(mode))

    def test_unrelated_speech_is_ignored_until_called(self):
        self.capri.on_final("открой ютуб", b"audio")
        self.assertTrue(self.capri.jobs.empty())
        self.capri.on_final("капри открой ютуб", b"audio")
        job = self.capri.jobs.get_nowait()
        self.assertEqual(job[1], "открой ютуб")

    def test_name_then_one_separate_phrase(self):
        self.capri.on_final("капри", b"name")
        self.assertGreater(self.capri.awake_until, time.time())
        self.capri.on_final("открой ютуб", b"audio")
        job = self.capri.jobs.get_nowait()
        self.assertEqual(job[1], "открой ютуб")
        self.capri.on_final("ещё какая-то фраза", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_no_followup_after_answer_even_with_old_config(self):
        self.capri.cfg["followup_seconds"] = 6
        self.capri.on_final("капри открой ютуб", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual(self.modes[-1], "idle")
        self.capri.on_final("открой почту", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_stop_closes_listening_and_requires_new_name(self):
        self.capri.on_final("капри", b"name")
        self.capri.on_partial("стоп")
        self.assertEqual(self.capri.awake_until, 0)
        self.assertEqual(self.modes[-1], "idle")
        self.capri.on_final("стоп", b"stop")
        self.capri.on_final("открой ютуб", b"audio")
        self.assertTrue(self.capri.jobs.empty())
        self.capri.on_final("капри открой ютуб", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "открой ютуб")

    def test_stop_with_name_is_not_queued_as_a_command(self):
        self.capri.on_final("капри стоп", b"audio")
        self.assertEqual(self.capri.awake_until, 0)
        self.assertTrue(self.capri.jobs.empty())

    def test_stop_discards_queued_voice_command(self):
        self.capri.on_final("капри открой ютуб", b"audio")
        self.capri.on_final("стоп", b"stop")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.actions.handle.assert_not_called()

    def test_stop_during_google_recognition_discards_result(self):
        self.capri.cfg["use_google_stt"] = True
        self.capri.on_final("капри открой ютуб", b"audio")

        def recognize(audio):
            self.capri.on_final("стоп", b"stop")
            return "капри открой ютуб"

        with patch.object(main, "google_stt", side_effect=recognize):
            self.capri._process(self.capri.jobs.get_nowait())
        self.capri.actions.handle.assert_not_called()

    def test_clear_commands_skip_google_but_questions_use_it(self):
        self.capri.cfg["use_google_stt"] = True
        self.capri.actions.is_fast_command.return_value = True
        self.capri.on_final("капри открой ютуб", b"audio")
        with patch.object(main, "google_stt") as recognize:
            self.capri._process(self.capri.jobs.get_nowait())
            recognize.assert_not_called()
        self.capri.actions.is_fast_command.return_value = False
        self.capri.on_final("капри почему небо голубое", b"audio")
        with patch.object(main, "google_stt", return_value=None) as recognize:
            self.capri._process(self.capri.jobs.get_nowait())
            recognize.assert_called_once_with(b"audio")

    def test_voice_correction_is_applied_before_google_and_dispatch(self):
        self.capri.cfg["use_google_stt"] = True
        self.capri.actions.normalize_voice_command.side_effect = lambda cmd: "следующий трек" if cmd == "текст" else cmd
        self.capri.actions.is_fast_command.side_effect = lambda cmd: cmd == "следующий трек"
        self.capri.on_final("капри текст", b"audio")
        with patch.object(main, "google_stt") as recognize:
            self.capri._process(self.capri.jobs.get_nowait())
        recognize.assert_not_called()
        self.capri.actions.handle.assert_called_once_with("следующий трек")

    def test_stop_during_ai_request_prevents_late_response(self):
        self.capri.actions.handle.return_value = None
        self.capri.local = Mock()

        def ask(question):
            self.capri.on_final("стоп", b"stop")
            return "Запоздалый ответ."

        self.capri.local.ask.side_effect = ask
        self.capri.on_final("капри расскажи что-нибудь", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.speaker.say.assert_not_called()
        self.assertEqual(self.capri.awake_until, 0)
        self.capri.speaker.stop.assert_called()

    def test_new_command_does_not_wait_for_stuck_ai(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        class SlowAI:
            def __init__(self):
                self.history = []

            def ask(self, question):
                started.set()
                release.wait(3)
                self.history.append({"role": "assistant", "content": "Запоздалый ответ"})
                finished.set()
                return "Запоздалый ответ"

        self.capri.local = SlowAI()
        self.capri.actions.handle.side_effect = lambda cmd: None if cmd == "объясни завод" else Reply("Переключила.")
        self.capri.say = Mock(return_value=False)
        self.capri.on_final("капри объясни завод", b"audio")
        worker = threading.Thread(target=self.capri._process, args=(self.capri.jobs.get_nowait(),), daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            self.capri.on_final("капри следующий трек", b"audio")
            worker.join(1)
            self.assertFalse(worker.is_alive(), "Новая команда ждёт зависший запрос ИИ")
            self.capri._process(self.capri.jobs.get_nowait())
            self.capri.say.assert_called_once_with("Переключила.")
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
            worker.join(1)
        self.assertEqual(self.capri.local.history, [])

    def test_streamed_sentences_speak_before_completion_without_repeating(self):
        first_spoken = threading.Event()
        completed = threading.Event()
        class StreamAI(main.LocalAI):
            def __init__(self):
                self.history = []
            def ask(self, question, on_sentence=None):
                on_sentence("Первая фраза.")
                if not first_spoken.wait(1):
                    raise RuntimeError("Первая фраза не озвучена во время генерации")
                on_sentence("Вторая фраза.")
                answer = "Первая фраза. Вторая фраза."
                self.history.append({"role": "assistant", "content": answer})
                completed.set()
                return answer
        self.capri.local = StreamAI()
        self.capri.actions.handle.return_value = None
        def say(text):
            if text == "Первая фраза.":
                self.assertFalse(completed.is_set())
                first_spoken.set()
            return False
        self.capri.say = Mock(side_effect=say)
        self.capri.on_final("капри расскажи что-нибудь", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual([c.args[0] for c in self.capri.say.call_args_list],
                         ["Первая фраза.", "Вторая фраза."])
        self.capri.speaker.prepare.assert_called_once_with("Вторая фраза.")
        self.assertTrue(completed.is_set())

    def test_router_command_bypasses_big_model_even_when_it_is_busy(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("next")
        self.capri.actions.handle.return_value = None
        self.capri.actions.execute_decision.return_value = Reply("Следующая песня.")
        self.capri.local = Mock()
        self.capri.say = Mock(return_value=False)
        self.capri.on_final("капри давай другую песню", b"audio")
        self.capri.ai_call_lock.acquire()
        worker = threading.Thread(target=self.capri._process, args=(self.capri.jobs.get_nowait(),), daemon=True)
        try:
            worker.start()
            worker.join(1)
            self.assertFalse(worker.is_alive())
        finally:
            self.capri.ai_call_lock.release()
            worker.join(1)
        self.capri.actions.execute_decision.assert_called_once_with(Decision("next"), original="давай другую песню")
        self.capri.local.ask.assert_not_called()

    def test_known_command_does_not_call_router(self):
        self.capri.router = Mock()
        self.capri.on_final("капри открой ютуб", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.router.ask.assert_not_called()

    def test_update_starts_helper_once_after_spoken_reply(self):
        self.capri.actions.handle.return_value = Reply("Обновляюсь.", "update")
        self.capri.say = Mock(return_value=False)
        process = Mock()
        process.poll.return_value = None
        with patch("main.updater.start_update", return_value=process) as start:
            for _ in range(2):
                self.capri.text_command("обновись")
                self.capri._process(self.capri.jobs.get_nowait())
            start.assert_called_once()

    def test_stop_during_stream_drops_remaining_sentences_and_history(self):
        completed = threading.Event()
        class StreamAI(main.LocalAI):
            def __init__(self):
                self.history = []
            def ask(self, question, on_sentence=None):
                on_sentence("Первая фраза.")
                on_sentence("Вторая фраза.")
                self.history.append({"role": "assistant", "content": "Запоздалый ответ"})
                completed.set()
                return "Первая фраза. Вторая фраза."
        self.capri.local = StreamAI()
        self.capri.actions.handle.return_value = None
        def stop(text):
            self.capri.stop_listening()
            return True
        self.capri.say = Mock(side_effect=stop)
        self.capri.on_final("капри расскажи что-нибудь", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertTrue(completed.wait(1))
        self.capri.say.assert_called_once_with("Первая фраза.")
        self.assertEqual(self.capri.local.history, [])

    def test_stop_interrupts_speech_even_with_barge_in_disabled(self):
        self.capri.cfg["barge_in"] = False
        self.capri.listener = Mock()
        self.capri.speaker.say.side_effect = lambda text: self.capri.on_partial("стоп")
        self.assertTrue(self.capri.say("Говорю длинную фразу."))
        self.capri.speaker.stop.assert_called()
        self.capri.listener.muted.set.assert_not_called()
        self.assertEqual(self.capri.awake_until, 0)

    def test_old_speech_words_do_not_block_stop(self):
        self.capri.speech_words = {"стоп"}
        self.capri.speech_end = time.time() - 5
        self.capri.on_final("капри", b"name")
        self.capri.on_final("стоп", b"stop")
        self.assertEqual(self.capri.awake_until, 0)

    def test_partial_name_opens_window_but_timeout_closes_it(self):
        self.capri.on_partial("капри")
        self.assertGreater(self.capri.awake_until, time.time())
        self.capri.awake_until = time.time() - 1
        self.capri.on_final("открой ютуб", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_long_phrase_extends_window_after_name(self):
        self.capri.awake_until = time.time() + 0.1
        self.capri.on_partial("расскажи мне подробнее про компьютер")
        self.assertGreater(self.capri.awake_until, time.time() + 7)
        self.capri.on_final("расскажи мне подробнее про компьютер", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "расскажи мне подробнее про компьютер")

    def test_echo_does_not_stop_own_speech(self):
        self.capri.speaking = True
        self.capri.speech_words = {"стоп"}
        self.capri.on_partial("стоп")
        self.assertEqual(self.capri.voice_generation, 0)

    def test_own_name_in_recent_speech_does_not_open_listening(self):
        self.capri.speech_words = {"капри", "онлайн"}
        self.capri.speech_end = time.time()
        self.capri.on_partial("капри")
        self.assertEqual(self.capri.awake_until, 0)


if __name__ == "__main__":
    unittest.main()
