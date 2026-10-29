"""Связность речи: числа, пояснения, завершённые предложения и разговорный стиль."""
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

import local_ai
import persona
import voice
from personality import Personality


def stream(*chunks):
    return io.BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))


class SpeechQualityTests(unittest.TestCase):
    def test_abrupt_stream_end_does_not_speak_unfinished_text(self):
        ai = local_ai.LocalAI({})
        spoken = []
        with patch("local_ai.urllib.request.urlopen", return_value=stream(
                {"message": {"content": "Этот ответ оборвался посреди длинного предложения и больше ничего не пришло"}})):
            self.assertIsNone(ai.ask("Объясни", on_sentence=spoken.append))
        self.assertEqual(spoken, [])
        self.assertEqual(ai.history, [])

    def test_abrupt_stream_keeps_only_already_completed_sentences(self):
        spoken = []
        with patch("local_ai.urllib.request.urlopen", return_value=stream(
                {"message": {"content": "Первое предложение завершено. Следующее оборвалось"}})):
            answer = local_ai.LocalAI({}).ask("Объясни", on_sentence=spoken.append)
        self.assertEqual(spoken, ["Первое предложение завершено."])
        self.assertEqual(answer, spoken[0])

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
    def test_casual_script_is_rare_and_preserves_target(self):
        target = "CS2 {name} 30"
        with patch.object(persona, "_CASUAL_TURN", 0), patch("persona.random.choice", side_effect=lambda values: values[0]):
            replies = [persona.line("open", t=target) for _ in range(24)]
        self.assertTrue(all(target in reply for reply in replies))
        self.assertEqual(sum("блядь" in reply for reply in replies), 0)
        self.assertEqual(len(persona.LINES["open"]), 10)
        self.assertNotIn("listen", persona.CASUAL_VARIANTS)
        self.assertNotIn("greet", persona.CASUAL_VARIANTS)

    def test_happy_mood_does_not_append_profanity_to_commands(self):
        person = Personality(persist=False)
        person.react("ты молодец")
        for _ in range(24):
            self.assertNotIn("Блядь", person.command_line("roam", "default"))
        self.assertFalse(person.strongly_hurt)
        self.assertIn("без мата", person.context())


class UncensoredVoiceTests(unittest.TestCase):
    def test_profanity_uses_selected_online_voice_and_effects(self):
        import numpy as np
        speaker = voice.Speaker({"voice": "ru-RU-SvetlanaNeural"})
        text = "Готово. Заебись."
        with patch("edge_tts.Communicate") as network, \
                patch("voice.decode", return_value=np.zeros(200, np.float32)), \
                patch("voice.write_wav") as output:
            network.return_value.save = AsyncMock()
            self.assertEqual(speaker.render(text, "voice.wav"), "voice.wav")
        self.assertEqual(network.call_count, 2)
        self.assertEqual([c.args[0] for c in network.call_args_list], ["Готово.", "Заебись."])
        self.assertTrue(all(c.args[1] == speaker.voice for c in network.call_args_list))
        output.assert_called_once()

    def test_profanity_does_not_use_old_windows_voice_cache(self):
        import hashlib
        speaker = voice.Speaker({})
        text = "Готово. Заебись."
        old_key = "|".join(map(str, (text, "sapi-profanity-v1", speaker.voice, speaker.rate,
            speaker.pitch, speaker.shift, speaker.lively, speaker.fx, speaker.volume, speaker.silero_voice)))
        self.assertNotIn(hashlib.sha1(old_key.encode()).hexdigest(), speaker._cache_path(text))

    def test_network_failure_keeps_fallback_for_all_text(self):
        for text in ("Готово.", "Заебись."):
            speaker = voice.Speaker({})
            with patch("voice.os.path.isfile", return_value=False), \
                    patch.object(speaker, "_edge", side_effect=RuntimeError("offline")), \
                    patch.object(speaker, "_sapi", return_value=False) as fallback:
                speaker.say(text)
            fallback.assert_called_once_with(text)
            self.assertGreater(speaker._edge_retry_at, 0)


if __name__ == "__main__":
    unittest.main()
