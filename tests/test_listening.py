"""Сценарии обращения по имени и остановки без микрофона, сети и интерфейса."""
import copy
import time
import threading
import unittest
from unittest.mock import Mock, patch

import main
from actions import Actions, Reply
from intent_router import Decision


class ListeningTests(unittest.TestCase):
    def setUp(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, use_google_stt=False, intent_router=False)
        with patch.object(main, "Actions"), patch.object(main, "Speaker"), \
                patch.object(main, "AI"), patch.object(main, "make_glitch_sound"):
            self.capri = main.Capri(cfg)
        self.capri.web = Mock()
        self.capri.web.ask.return_value = []
        self.capri.reload_config_if_changed = Mock()
        self.capri.actions.handle.return_value = Reply("Готово.")
        self.capri.actions.is_fast_command.return_value = False
        self.capri.actions.normalize_voice_command.side_effect = lambda cmd: cmd
        self.capri.actions.stop_background.return_value = False
        self.capri.actions.pending = None
        self.capri.actions.choice = None
        self.capri._check_voice_blocked = Mock()
        self.modes = []
        self.capri.mode.connect(lambda mode, seconds: self.modes.append(mode))

    def test_name_in_game_appears_with_sound_before_command_processing(self):
        self.capri.game_active = True
        self.capri.glitch_wav = "appearance.wav"
        with patch("main.play_sound_async") as sound, patch.object(self.capri, "_ask_ai") as ai:
            self.capri.on_partial("капри")
            self.assertIn("listening", self.modes)
            sound.assert_called_once_with("appearance.wav")
            ai.assert_not_called()
        self.assertTrue(self.capri.jobs.empty())

    def test_final_wake_command_appears_even_without_partial_result(self):
        with patch.object(self.capri, "appear") as appear:
            self.capri.on_final("капри поставь лайк песне", b"audio")
        appear.assert_called_once()
        self.assertEqual(self.capri.jobs.get_nowait()[1], "поставь лайк песне")

    def test_failed_chat_answer_never_triggers_search(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("chat")
        self.capri.actions.handle_conversation.return_value = None
        self.capri.local = Mock()
        self.capri.local.ask.return_value = None
        self.capri.ai.available = False
        self.capri.say = Mock(return_value=False)
        for phrase in ("давай поговорим", "почему небо голубое", "расскажи анекдот"):
            self.capri.text_command(phrase)
            self.capri._process(self.capri.jobs.get_nowait())
        self.capri.web.ask.assert_not_called()
        self.capri.actions.web.assert_not_called()
        self.assertEqual(self.capri.router.ask.call_count, 3)
        self.assertEqual(self.capri.local.ask.call_count, 3)

    def test_router_search_preserves_whole_question_and_runs_before_answer(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("search", "Франция")
        self.capri.actions.handle.return_value = None
        self.capri.actions.execute_decision.return_value = Reply("Франция", "research")
        self.capri.local = Mock()
        self.capri.local.ask.return_value = "Ответ по найденным сведениям."
        self.capri.ai.available = False
        sources = [{"title": "Источник", "url": "https://example.org/", "text": "Проверенные сведения."}]
        self.capri.web.ask.return_value = sources
        self.capri.say = Mock(return_value=False)
        self.capri.text_command("Кто сейчас президент Франции?")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.web.ask.assert_called_once_with("Кто сейчас президент Франции?")
        self.capri.local.ask.assert_called_once_with("Кто сейчас президент Франции?", web_context=sources)

    def test_model_failure_does_not_read_raw_web_snippet_or_site(self):
        self.capri.actions.handle.return_value = Reply("тема", "research")
        self.capri.ai.available = False
        self.capri.local = Mock()
        self.capri.local.ask.return_value = None
        self.capri.web.ask.return_value = [{"title": "Some Site", "url": "https://example.org/", "text": "Сырой фрагмент статьи."}]
        self.capri.say = Mock(return_value=False)
        self.capri.text_command("найди информацию о теме")
        self.capri._process(self.capri.jobs.get_nowait())
        spoken = self.capri.say.call_args.args[0]
        self.assertNotIn("example.org", spoken)
        self.assertNotIn("Сырой фрагмент", spoken)
        self.assertIn("не смогла", spoken)

    def test_search_failure_is_spoken_without_opening_a_browser(self):
        self.capri.local = Mock()
        self.capri.local.ask.return_value = None
        self.capri.ai.available = False
        self.capri.actions.handle.return_value = Reply("Какая погода сегодня?", "research")
        self.capri.say = Mock(return_value=False)
        self.capri.text_command("Какая погода сегодня?")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.web.ask.assert_called_once()
        self.capri.actions.web.assert_not_called()
        self.capri.actions.fallback.assert_not_called()
        self.assertIn("Не удалось получить сведения", self.capri.say.call_args.args[0])

    def test_automatic_search_can_be_disabled_without_opening_browser(self):
        self.capri.cfg["search_when_unsure"] = False
        self.capri.local = Mock()
        self.capri.local.ask.return_value = None
        self.capri.ai.available = False
        self.capri.actions.handle.return_value = None
        self.capri.actions.fallback.return_value = Reply("Не знаю ответа.")
        self.capri.say = Mock(return_value=False)
        self.capri.text_command("Вопрос")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.web.ask.assert_not_called()
        self.capri.actions.web.assert_not_called()
        self.capri.say.assert_called_once_with("Не знаю ответа.")

    def test_explicit_research_skips_uninformed_answer_and_remains_cancellable(self):
        self.capri.actions.handle.return_value = Reply("история Python", "research")
        self.capri.ai.available = False
        completed = threading.Event()
        def fetch(question):
            self.capri.stop_listening()
            completed.set()
            return [{"title": "Python", "url": "https://python.org/", "text": "Поздний результат."}]
        self.capri.web.ask.side_effect = fetch
        self.capri.local = Mock()
        self.capri.say = Mock(return_value=False)
        self.capri.on_final("капри найди информацию про Python", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertTrue(completed.wait(1))
        self.capri.local.ask.assert_not_called()
        self.capri.say.assert_not_called()
        self.assertEqual(self.capri.last_web_sources, [])

    def test_question_accepts_one_reply_without_name(self):
        self.capri.actions.handle.return_value = Reply("Какую музыку ты любишь?")
        self.capri.on_final("капри поговорим", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual(self.modes[-1], "listening")
        self.assertGreater(self.capri.answer_until, time.time())
        self.capri.on_final("люблю рок", b"audio")
        job = self.capri.jobs.get_nowait()
        self.assertEqual(job[1], "люблю рок")
        self.assertEqual(self.capri.answer_until, 0)
        self.capri.on_final("посторонняя речь", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_confirmation_opens_window_even_without_question_mark(self):
        pending = Mock()
        self.capri.actions.pending = pending
        self.capri.finish_reply("Подтверди действие словами да или нет.")
        self.capri.on_final("да", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "да")
        self.assertIs(self.capri.actions.pending, pending)
        pending.assert_not_called()

    def test_choice_opens_window_and_accepts_number(self):
        self.capri.actions.choice = [("one", "one.exe"), ("two", "two.exe")]
        self.capri.finish_reply("Есть два приложения. Назови номер.")
        self.capri.on_final("второе", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "второе")
        self.assertIsNotNone(self.capri.actions.choice)

    def test_reply_window_starts_after_full_stream_only(self):
        capri = self.capri
        windows = []
        class StreamAI(main.LocalAI):
            def __init__(self):
                self.history = []
            def ask(self, question, on_sentence=None):
                on_sentence("Хочешь поговорить?")
                on_sentence("Что тебя интересует?")
                return "Хочешь поговорить? Что тебя интересует?"
        capri.local = StreamAI()
        capri.ai.available = False
        capri.actions.handle.return_value = None
        capri.speaker.say.side_effect = lambda text: windows.append(capri.answer_until)
        capri.on_final("капри привет", b"audio")
        capri._process(capri.jobs.get_nowait())
        self.assertEqual(windows, [0, 0])
        self.assertGreater(capri.answer_until, time.time())
        self.assertEqual(self.modes[-1], "listening")

    def test_timeout_clears_pending_confirmation_and_choice(self):
        self.capri.actions.pending = Mock()
        self.capri.actions.choice = [("one", "one.exe")]
        self.capri.finish_reply("Подтверждаешь?")
        self.capri.expire_answer(self.capri.answer_until + 1)
        self.assertIsNone(self.capri.actions.pending)
        self.assertIsNone(self.capri.actions.choice)
        self.assertEqual(self.capri.awake_until, 0)
        self.capri.on_final("да", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_short_answer_is_not_rejected_as_question_echo(self):
        self.capri.speech_words = {"да", "или", "нет"}
        self.capri.speech_end = time.time()
        self.capri.finish_reply("Да или нет?")
        self.capri.on_final("да", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "да")

    def test_long_answer_keeps_pending_choice_alive(self):
        self.capri.actions.choice = [("one", "one.exe")]
        self.capri.finish_reply("Какое?")
        self.capri.answer_until = self.capri.awake_until = time.time() + 0.1
        self.capri.on_partial("хочу выбрать первое приложение")
        self.assertGreater(self.capri.answer_until, time.time() + 7)
        self.capri.expire_answer()
        self.assertIsNotNone(self.capri.actions.choice)

    def test_stop_cancels_reply_window(self):
        self.capri.finish_reply("Как дела?")
        self.capri.on_partial("стоп")
        self.assertEqual(self.capri.answer_until, 0)
        self.capri.on_final("хорошо", b"audio")
        self.assertTrue(self.capri.jobs.empty())

    def test_question_in_standalone_phrase_also_opens_window(self):
        self.capri._process(("say", "Как настроение?"))
        self.assertGreater(self.capri.answer_until, time.time())
        self.assertEqual(self.modes[-1], "listening")

    def test_question_can_be_followed_by_a_statement(self):
        self.capri.finish_reply("Хочешь поговорить? Я рядом.")
        self.assertGreater(self.capri.answer_until, time.time())

    def test_explicit_ask_opens_window_without_punctuation(self):
        self.capri.finish_reply("Назови нужный вариант.", ask=True)
        self.assertGreater(self.capri.answer_until, time.time())

    def test_confirmation_answer_skips_google_retry(self):
        self.capri.cfg["use_google_stt"] = True
        self.capri.actions.pending = Mock()
        self.capri.finish_reply("Подтверждаешь?")
        self.capri.on_final("да", b"audio")
        with patch.object(main, "google_stt") as google:
            self.capri._process(self.capri.jobs.get_nowait())
        google.assert_not_called()

    def test_short_answer_can_repeat_the_last_question_word(self):
        self.capri.speech_words = {"первое"}
        self.capri.speech_end = time.time()
        self.capri.finish_reply("Первое?")
        self.capri.on_final("первое", b"audio")
        self.assertEqual(self.capri.jobs.get_nowait()[1], "первое")

    def test_nap_animation_starts_after_speech(self):
        animations = []
        self.capri.anim.connect(animations.append)
        self.capri.actions.handle.return_value = Reply("Немного подремлю.", "anim:sleep")
        self.capri.speaker.say.side_effect = lambda text: self.assertEqual(animations, [])
        self.capri.on_final("капри поспи", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual(animations, ["sleep"])

    def test_voice_tone_settings_preserve_other_config_fields(self):
        saved = {"mic_device": "user microphone", "user_name": "user"}
        with patch.object(main, "_edit_config", side_effect=lambda change: change(saved)):
            self.capri.set_voice_tone(shift=3, glitch=.25)
        self.assertEqual(saved["voice_shift"], 3)
        self.assertEqual(saved["voice_glitch"], .25)
        self.assertEqual(saved["mic_device"], "user microphone")
        self.assertEqual(saved["user_name"], "user")
        self.assertEqual(self.capri.speaker.shift, 3)
        self.assertEqual(self.capri.speaker.glitch, .25)

    def test_dismissal_waits_for_full_sentence_and_hides_without_speech(self):
        self.capri.on_partial("капри заткнись")
        self.assertGreater(self.capri.awake_until, time.time())
        hidden = []
        self.capri.vanish.connect(lambda: hidden.append(True))
        self.capri.on_final("капри заткнись пожалуйста", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual(hidden, [True])
        self.assertEqual(self.capri.awake_until, 0)
        self.capri.speaker.say.assert_not_called()
        self.capri.actions.handle.assert_not_called()

    def test_negative_and_quoted_dismissals_cannot_reach_action_router(self):
        self.capri.router = Mock()
        self.capri.ai.available = False
        for text in ("капри не закрывайся", "капри что значит слово заткнись", "капри он сказал «закройся»"):
            self.capri.on_final(text, b"audio")
            self.capri._process(self.capri.jobs.get_nowait())
        self.capri.actions.handle.assert_not_called()
        self.assertEqual(self.capri.router.ask.call_count, 3)

    def test_ambiguous_request_uses_context_classifier(self):
        self.capri.router = main.IntentRouter({})
        hidden = []
        self.capri.vanish.connect(lambda: hidden.append(True))
        with patch.object(self.capri.router, "ask", return_value=Decision("hide")) as classify:
            self.capri.on_final("капри ты мне мешаешь закройся уже", b"audio")
            self.capri._process(self.capri.jobs.get_nowait())
        self.assertEqual(classify.call_args.args[0], "ты мне мешаешь закройся уже")
        self.assertEqual(hidden, [True])

    def test_name_interrupt_immediately_refreshes_avatar(self):
        self.capri.speaking = True
        self.capri.speaker.playing = False
        with patch.object(self.capri, "appear") as appear:
            self.capri.on_partial("эй,капри")
        appear.assert_called_once()
        self.assertGreater(self.capri.awake_until, time.time())

    def test_unrelated_speech_is_ignored_until_called(self):
        self.capri.on_final("открой ютуб", b"audio")
        self.assertTrue(self.capri.jobs.empty())
        self.capri.on_final("капри открой ютуб", b"audio")
        job = self.capri.jobs.get_nowait()
        self.assertEqual(job[1], "открой ютуб")

    def test_name_during_synthesis_is_not_mistaken_for_echo(self):
        self.capri.speaking = True
        self.capri.speech_words = {"капри", "онлайн"}
        self.capri.speaker.playing = False
        self.capri.on_partial("капри")
        self.capri.speaker.stop.assert_called_once()
        self.assertGreater(self.capri.awake_until, time.time())

    def test_repeated_name_refreshes_avatar_while_listening(self):
        self.capri.awake_until = time.time() + 8
        self.capri.last_partial_wake = time.time() - 4
        with patch.object(self.capri, "appear") as appear:
            self.capri.on_partial("капри")
        appear.assert_called_once()

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

    def test_known_command_calls_router_before_execution(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("command")
        order = []
        self.capri.router.ask.side_effect = lambda *a, **kw: order.append("router") or Decision("command")
        self.capri.actions.handle.side_effect = lambda cmd: order.append("execute") or Reply("Готово.")
        self.capri.on_final("капри открой ютуб", b"audio")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.router.ask.assert_called_once()
        self.assertEqual(order, ["router", "execute"])

    def test_chat_never_reaches_computer_commands(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("chat")
        self.capri.actions.handle_conversation.return_value = None
        self.capri.local = Mock()
        self.capri.local.ask.return_value = "Объяснение."
        self.capri.ai.available = False
        self.capri.text_command("Как выключить компьютер?")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.router.ask.assert_called_once()
        self.capri.actions.handle.assert_not_called()
        self.capri.actions.execute_decision.assert_not_called()
        self.capri.local.ask.assert_called_once_with("Как выключить компьютер?")

    def test_confirmation_stays_raw_after_router(self):
        self.capri.router = Mock()
        self.capri.router.ask.return_value = Decision("music")
        self.capri.actions.pending = Mock()
        self.capri.text_command("нет")
        self.capri._process(self.capri.jobs.get_nowait())
        self.capri.actions.handle.assert_called_once_with("нет")
        self.capri.actions.execute_decision.assert_not_called()
        self.assertTrue(self.capri.router.ask.call_args.kwargs["context"]["awaiting_confirmation"])

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


class ConfirmationTests(unittest.TestCase):
    def test_negative_reply_never_executes_pending_action(self):
        actions = Actions.__new__(Actions)
        for text in ("нет", "да не надо", "да я не хочу", "конечно нет"):
            pending = Mock(return_value=Reply("done"))
            actions.pending = pending
            actions.handle(text)
            pending.assert_not_called()
            self.assertIsNone(actions.pending)

    def test_explicit_affirmative_executes_once(self):
        actions = Actions.__new__(Actions)
        for text in ("да", "ага", "подтверждаю", "да выключай", "да давай"):
            pending = Mock(return_value=Reply("done"))
            actions.pending = pending
            self.assertEqual(actions.handle(text).text, "done")
            pending.assert_called_once()
            self.assertIsNone(actions.pending)


if __name__ == "__main__":
    unittest.main()
