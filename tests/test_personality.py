"""Настроение не вызывает ИИ, не подменяет команды и не требует фоновых таймеров."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from intent_router import Decision
from unittest.mock import Mock, patch

from actions import Actions, Reply
from ai import AI
from local_ai import LocalAI
import main
from personality import ANGRY_CONTEXT, ANGRY_REPLIES, ANGRY_COMMAND_LINES, Personality


class PersonalityTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.person = Personality(clock=lambda: self.now, persist=False)

    def test_greeting_and_talk_are_answered_locally(self):
        for phrase in ("привет", "давай поговорим", "поболтаем"):
            self.assertTrue(self.person.can_handle(phrase))
            reply = self.person.react(phrase).reply
            self.assertTrue(reply)
            self.assertNotIn("сайт", reply)

    def test_misunderstood_insult_is_a_local_reaction_not_a_search_request(self):
        phrase = "ты чмо иди на хер"
        self.assertTrue(self.person.can_handle(phrase))
        self.assertTrue(self.person.react(phrase).reply)
        self.assertTrue(self.person.strongly_hurt)
        other = Personality(persist=False)
        self.assertIsNone(other.react("найди фразу ты чмо иди на хер").reply)
        self.assertFalse(other.strongly_hurt)

    def test_hurt_expires_and_apology_reconciles_immediately(self):
        reaction = self.person.react("Ты тупая!")
        self.assertTrue(reaction.reply)
        self.assertEqual(self.person.mood, "hurt")
        self.now += 91
        self.assertEqual(self.person.mood, "neutral")
        self.person.react("дура")
        self.person.react("извини")
        self.assertEqual(self.person.mood, "neutral")

    def test_repeated_insults_are_bounded(self):
        for _ in range(20):
            self.person.react("ты бесполезная")
        self.assertEqual(self.person._strikes, 3)
        self.now += 271
        self.assertEqual(self.person.mood, "neutral")

    def test_hard_swearing_requires_severe_offense(self):
        for _ in range(2):
            reply = self.person.react("ты тупая").reply
            self.assertFalse(self.person.strongly_hurt)
            self.assertNotIn(reply, ANGRY_REPLIES)
            self.assertNotIn(ANGRY_CONTEXT, self.person.context())
        reply = self.person.react("ты тупая").reply
        self.assertTrue(self.person.strongly_hurt)
        self.assertIn(reply, ANGRY_REPLIES)
        self.assertIn(ANGRY_CONTEXT, self.person.context())

    def test_direct_send_off_triggers_angry_reply_and_apology_stops_it(self):
        for phrase in ("иди нахуй", "пошла ты нахуй", "да иди ты на хуй", "пошла в пизду"):
            with self.subTest(phrase=phrase):
                reaction = self.person.react(phrase)
                self.assertTrue(self.person.strongly_hurt)
                self.assertIn(reaction.reply, ANGRY_REPLIES)
                self.assertEqual(self.person.command_line("roam", "default"), ANGRY_COMMAND_LINES["roam"])
                self.person.react("извини")
                self.assertFalse(self.person.strongly_hurt)
                self.assertNotIn(ANGRY_CONTEXT, self.person.context())

    def test_roleplay_request_alone_cannot_unlock_swearing(self):
        for _ in range(10):
            self.person.react("обидься")
        self.assertFalse(self.person.strongly_hurt)
        self.assertIsNone(self.person.react("матерись").reply)
        self.assertIsNone(self.person.react("обматери меня").reply)

    def test_severe_offense_expires_and_titles_do_not_trigger_it(self):
        self.person.react("найди песню пошла ты нахуй")
        self.assertFalse(self.person.strongly_hurt)
        self.person.react("пошла ты нахуй")
        self.now += 271
        self.assertFalse(self.person.strongly_hurt)
        self.assertNotIn(ANGRY_CONTEXT, self.person.context())
        self.assertNotEqual(self.person.command_line("roam", "default"), ANGRY_COMMAND_LINES["roam"])

    def test_severe_prefix_keeps_computer_command(self):
        reaction = self.person.react("иди нахуй, включи музыку")
        self.assertTrue(self.person.strongly_hurt)
        self.assertEqual(reaction.command, "включи музыку")
        self.assertIsNone(reaction.reply)

    def test_praise_teasing_and_jokes_change_tone(self):
        for phrase, expected in (("ты молодец", "happy"), ("ты вредина", "playful"),
                                 ("дура", "hurt"), ("я шучу", "playful")):
            with self.subTest(phrase=phrase):
                self.assertTrue(self.person.react(phrase).reply)
                self.assertEqual(self.person.mood, expected)

    def test_mood_query_does_not_change_emotion(self):
        self.person.react("ты глупая")
        answer = self.person.react("ты обиделась?")
        self.assertTrue(answer.reply)
        self.assertEqual(self.person.mood, "hurt")

    def test_search_titles_negation_and_stop_do_not_cause_offense(self):
        for phrase in ("найди песню ты тупая", "открой приложение дура", "ты не тупая", "стоп",
                       "расскажи почему люди обижаются", "книга спасибо, включи музыку"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(self.person.react(phrase).reply)
                self.assertEqual(self.person.mood, "neutral")

    def test_social_prefix_preserves_command_and_changes_mood(self):
        reaction = self.person.react("ты тупая, включи музыку")
        self.assertEqual(reaction.command, "включи музыку")
        self.assertIsNone(reaction.reply)
        self.assertEqual(self.person.mood, "hurt")
        reaction = self.person.react("извини; громкость cs2 30")
        self.assertEqual(reaction.command, "громкость cs2 30")
        self.assertEqual(self.person.mood, "neutral")

    def test_local_replies_do_not_repeat_immediately(self):
        first = self.person.react("спасибо").reply
        self.assertNotEqual(self.person.react("спасибо").reply, first)

    def test_thanks_softens_offense_and_joke_request_is_local(self):
        self.person.react("ты тупая")
        self.person.react("спасибо")
        self.assertEqual(self.person.mood, "neutral")
        self.assertTrue(self.person.react("расскажи шутку").reply)
        self.assertEqual(self.person.mood, "playful")

    def test_disabled_personality_does_not_touch_files_or_commands(self):
        self.person.enabled = False
        with patch.object(self.person, "_save") as save:
            reaction = self.person.react("ты тупая, включи музыку")
        self.assertEqual(reaction.command, "ты тупая, включи музыку")
        self.assertIsNone(reaction.reply)
        self.assertEqual(self.person.context(), "")
        save.assert_not_called()

    def test_only_small_state_is_saved_and_expired_state_is_not_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mood.json"
            person = Personality(path=path, clock=lambda: self.now)
            person.react("ты тупая")
            data = json.loads(path.read_text())
            self.assertEqual(set(data), {"mood", "until", "strikes"})
            self.assertEqual(Personality(path=path, clock=lambda: self.now).mood, "hurt")
            self.now += 600
            self.assertEqual(Personality(path=path, clock=lambda: self.now).mood, "neutral")

    def test_corrupt_state_cannot_break_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mood.json"
            for content in ('[]', '{"mood":[],"until":1100,"strikes":1}',
                            '{"mood":"hurt","until":NaN,"strikes":1}', '{broken'):
                path.write_text(content)
                self.assertEqual(Personality(path=path, clock=lambda: self.now).mood, "neutral")

    def test_both_chat_backends_receive_current_mood_without_extra_request(self):
        self.person.react("ты тупая")
        for ai in (AI({}), LocalAI({})):
            ai.personality = self.person
            self.assertIn("обижена", ai._context())
            self.person.react("извини")
            self.assertNotIn("обижена", ai._context())
            self.person.react("ты тупая")


class PersonalityCommandTests(unittest.TestCase):
    def setUp(self):
        with patch("actions.AppIndex.build"):
            self.actions = Actions({}, ".", None)
        self.actions.personality = Personality(persist=False)

    def test_hurt_does_not_block_actual_command(self):
        self.actions.handle("ты тупая")
        with patch.object(self.actions, "media_next", return_value=Reply("Следующий трек")) as next_track:
            # routes хранят связанные обработчики, поэтому заменяем соответствующий маршрут.
            self.actions.routes = [(r"^следующий трек$", next_track)]
            reply = self.actions.handle("следующий трек")
        next_track.assert_called_once()
        self.assertEqual(reply.text, "Следующий трек")

    def test_social_reply_does_not_leave_dangerous_confirmation_pending(self):
        pending = Mock()
        self.actions.pending = pending
        self.actions.handle("извини")
        self.assertIsNone(self.actions.pending)
        self.actions.handle("да")
        pending.assert_not_called()

    def test_mood_changes_acknowledgment_but_not_motion_action(self):
        neutral = self.actions.handle("походи")
        self.actions.handle("ты тупая")
        hurt = self.actions.handle("походи")
        self.assertEqual(neutral.action, "roam")
        self.assertEqual(hurt.action, "roam")
        self.assertNotEqual(neutral.text, hurt.text)

    def test_social_reply_is_not_fuzzy_matched_to_a_program_choice(self):
        launch = Mock()
        self.actions.choice = [("тупая", launch)]
        self.actions.handle("ты тупая")
        launch.assert_not_called()
        self.assertIsNone(self.actions.choice)
        self.assertEqual(self.actions.personality.mood, "hurt")

    def test_social_request_passes_router_but_skips_google_and_big_model(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, intent_router=False, use_google_stt=True)
        with patch.object(main, "Actions", return_value=self.actions), patch.object(main, "Speaker"), \
                patch.object(main, "AI"), patch.object(main, "Personality", return_value=Personality(persist=False)), \
                patch.object(main, "make_glitch_sound"):
            capri = main.Capri(cfg)
        capri.router = Mock()
        capri.local = Mock()
        capri.say = Mock(return_value=False)
        capri.reload_config_if_changed = Mock()
        with patch.object(main, "google_stt") as google, patch.object(capri, "_ask_ai", return_value=Decision("chat")) as ai:
            capri._process(("voice", "ты тупая", b"audio", True, 0))
        self.assertEqual(capri.personality.mood, "hurt")
        capri.say.assert_called_once()
        google.assert_not_called()
        ai.assert_called_once()
        self.assertIs(ai.call_args.args[0], capri.router)
        capri.local.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
