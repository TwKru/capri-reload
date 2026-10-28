"""Связность речи: числа, пояснения, завершённые предложения и разговорный стиль."""
import io
import json
import unittest
from unittest.mock import patch

import local_ai
import persona
import voice
from personality import Personality


def stream(*chunks):
    return io.BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))


class SpeechQualityTests(unittest.TestCase):
    def test_decimal_abbreviations_and_parentheses_stay_together(self):
        parts = local_ai.complete_sentences("Это 3.14 (т. е. число). Следующее предложение.", final=True)
        self.assertEqual(parts, ["Это 3.14 (т. е. число).", "Следующее предложение."])

    def test_partial_decimal_is_not_spoken_early(self):
        self.assertEqual(local_ai.complete_sentences("Значение 3."), [])
        self.assertEqual(local_ai.complete_sentences("Значение 3.14. След"), ["Значение 3.14."])

    def test_normal_intro_is_not_mistaken_for_internal_reasoning(self):
        self.assertIsNone(local_ai.REASONING.search("Хорошо, давай разберёмся."))
        self.assertIsNone(local_ai.REASONING.search("Давайте разберём пример."))
        self.assertIsNotNone(local_ai.REASONING.search("Пользователь спрашивает про компьютер."))

    def test_stream_preserves_technical_explanation_and_quotes(self):
        chunks = ({"message": {"content": "Это 3."}},
                  {"message": {"content": "14 (т. е. число). Следующее "}},
                  {"message": {"content": "предложение."}, "done": True})
        spoken = []
        with patch("local_ai.urllib.request.urlopen", return_value=stream(*chunks)):
            answer = local_ai.LocalAI({}).ask("Объясни", on_sentence=spoken.append)
        self.assertEqual(spoken, ["Это 3.14 (т. е. число).", "Следующее предложение."])
        self.assertEqual(answer, " ".join(spoken))
        with patch("local_ai.urllib.request.urlopen", return_value=stream(
                {"message": {"content": "Она сказала: «Привет!»"}, "done": True})):
            self.assertEqual(local_ai.LocalAI({}).ask("Пример", on_sentence=lambda _: None), "Она сказала: «Привет!»")

    def test_token_limit_does_not_speak_an_unfinished_tail(self):
        chunk = {"message": {"content": "Первое предложение закончено. Второе предложение оборвалось на"},
                 "done": True, "done_reason": "length"}
        spoken = []
        with patch("local_ai.urllib.request.urlopen", return_value=stream(chunk)):
            answer = local_ai.LocalAI({}).ask("Объясни", on_sentence=spoken.append)
        self.assertEqual(spoken, ["Первое предложение закончено."])
        self.assertEqual(answer, spoken[0])

    def test_factual_parentheses_and_repeated_answer_are_not_deleted(self):
        text = "Видеопамять (VRAM) хранит текстуры."
        history = [{"role": "assistant", "content": text}]
        self.assertEqual(local_ai.LocalAI._clean_answer(text, "Повтори", history), text)
        self.assertEqual(local_ai.drop_repeats("Один ответ. Один ответ.", []), "Один ответ.")

    def test_dangling_assistant_message_is_not_sent_as_first_turn(self):
        ai = local_ai.LocalAI({})
        ai.history = [{"role": "assistant", "content": "Старый ответ."},
                      {"role": "user", "content": "Первый вопрос"},
                      {"role": "assistant", "content": "Первый ответ."}]
        with patch("local_ai._post", return_value={"message": {"content": "Новый ответ."}}) as request:
            ai.ask("Следующий вопрос")
        messages = request.call_args.args[1]["messages"]
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[-3]["content"], "Первый вопрос")
        self.assertNotIn("Старый ответ.", [m["content"] for m in messages])
        self.assertEqual(messages[-1]["content"], "Следующий вопрос")

    def test_model_stop_without_punctuation_is_still_a_valid_answer(self):
        with patch("local_ai._post", return_value={"message": {"content": "Конечно"}, "done_reason": "stop"}):
            self.assertEqual(local_ai.LocalAI({}).ask("Поможешь?"), "Конечно.")


class CasualStyleTests(unittest.TestCase):
    def test_casual_script_happens_regularly_and_preserves_target(self):
        target = "CS2 {name} 30"
        with patch.object(persona, "_CASUAL_TURN", 0), patch("persona.random.choice", side_effect=lambda values: values[0]):
            first = persona.line("open", t=target)
            second = persona.line("open", t=target)
        self.assertIn(target, first)
        self.assertIn(target, second)
        self.assertNotIn("блядь", first)
        self.assertIn("блядь", second)

    def test_happy_mood_does_not_override_all_casual_variants(self):
        person = Personality(persist=False)
        person.react("ты молодец")
        first = person.command_line("roam", "default")
        second = person.command_line("roam", "default")
        self.assertNotIn("Блядь", first)
        self.assertIn("Блядь", second)
        self.assertFalse(person.strongly_hurt)
        self.assertIn("без оскорблений", person.context())


class UncensoredVoiceTests(unittest.TestCase):
    def test_profanity_uses_local_render_without_network(self):
        speaker = voice.Speaker({})
        for text in ("Готово. Заебись.", "Ебучий браузер опять завис.", "Охуенно.", "Хуёвый день."):
            with self.subTest(text=text), patch.object(speaker, "render_sapi", return_value="local.wav") as local, \
                    patch("edge_tts.Communicate") as network:
                self.assertEqual(speaker.render(text, "local.wav"), "local.wav")
            local.assert_called_once_with(text, "local.wav")
            network.assert_not_called()

    def test_local_speech_works_during_outage_without_resetting_network_health(self):
        speaker = voice.Speaker({})
        speaker._edge_retry_at = float("inf")
        speaker.edge_error = "network unavailable"
        with patch("voice.os.path.isfile", return_value=False), patch.object(speaker, "_edge", return_value=False) as render:
            speaker.say("Готово. Заебись.")
        render.assert_called_once()
        self.assertEqual(speaker.edge_error, "network unavailable")
        self.assertEqual(speaker._edge_retry_at, float("inf"))

    def test_plain_speech_keeps_its_normal_backend(self):
        speaker = voice.Speaker({})
        self.assertFalse(speaker._local_profanity("Открываю программу CS2."))
        self.assertFalse(speaker._local_profanity("Подстрахуй меня."))


if __name__ == "__main__":
    unittest.main()
