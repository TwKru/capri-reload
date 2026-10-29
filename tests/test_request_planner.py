import io
import json
import string
import unittest
from unittest.mock import patch

from action_replies import ACTION_REPLIES
from intent_router import COMMAND_SCHEMA, IntentRouter
from request_planner import RequestPlan, compact_sources, fallback_plan
import persona


SOURCES = [{"title": "Прогноз", "url": "https://example.org/", "text": "Сейчас минус 5 градусов. Завтра будет снег."}]


def response(data):
    return io.BytesIO(json.dumps({"message": {"content": json.dumps(data)}}).encode())


class PlanTests(unittest.TestCase):
    def test_first_schema_cannot_launch_web_search(self):
        self.assertNotIn("search", COMMAND_SCHEMA["properties"]["action"]["enum"])

    def test_second_stage_really_calls_mini_model_for_local_and_web(self):
        for route, question, query in (("local", "Почему небо голубое?", ""),
                                       ("web", "Погода в Краснообске", "погода в Краснообске сейчас")):
            with patch("intent_router.urllib.request.urlopen", return_value=response(
                    {"route": route, "complexity": "simple", "query": query})) as call:
                plan = IntentRouter({}).assess(question)
            self.assertEqual(plan.route, route)
            payload = json.loads(call.call_args.args[0].data)
            self.assertFalse(payload["think"])
            self.assertIn(question, payload["messages"][-1]["content"])

    def test_social_text_cannot_become_web_even_if_model_mistakes(self):
        with patch("intent_router.urllib.request.urlopen", return_value=response(
                {"route": "web", "complexity": "simple", "query": "фильм Давай поговорим"})):
            self.assertEqual(IntentRouter({}).assess("давай поговорим").route, "local")

    def test_explicit_weather_cannot_be_lost_by_wrong_local_assessment(self):
        with patch("intent_router.urllib.request.urlopen", return_value=response(
                {"route": "local", "complexity": "simple", "query": ""})):
            plan = IntentRouter({}).assess("Какая погода в Краснообске?")
        self.assertEqual(plan.route, "web")
        self.assertIn("Краснообске", plan.query)

    def test_currency_quote_needs_web_but_definition_does_not(self):
        with patch("intent_router.urllib.request.urlopen", return_value=response(
                {"route": "local", "complexity": "simple", "query": ""})):
            self.assertEqual(IntentRouter({}).assess("Какой курс доллара сегодня?").route, "web")
        self.assertEqual(fallback_plan("Что такое курс доллара?").route, "local")

    def test_invalid_plan_and_failed_second_stage_cannot_execute_commands(self):
        for data in ({"route": "shutdown", "complexity": "simple", "query": ""},
                     {"route": "web", "complexity": "simple", "query": ""},
                     {"route": "web", "complexity": "simple", "query": "a\nsecond"},
                     {"route": "local", "complexity": "simple", "query": "", "shell": "cmd"}):
            with self.assertRaises(ValueError):
                RequestPlan.parse(data)
        with patch("intent_router.urllib.request.urlopen", side_effect=TimeoutError):
            self.assertIsNone(IntentRouter({}).assess("Простой вопрос"))
        self.assertEqual(fallback_plan("давай поговорим").route, "local")
        self.assertEqual(fallback_plan("погода в Краснообске").route, "web")

    def test_generated_query_preserves_subject_numbers_city_and_time(self):
        self.assertEqual(RequestPlan("web", "simple", "Франция").search_query("Кто сейчас президент Франции?"),
                         "Кто сейчас президент Франции?")
        self.assertEqual(RequestPlan("web", "simple", "погода в Краснообске").search_query("Погода завтра в Краснообске"),
                         "Погода завтра в Краснообске")
        self.assertEqual(RequestPlan("web", "simple", "цена видеокарты RTX 4060").search_query("Цена RTX 2060"), "Цена RTX 2060")
        self.assertEqual(RequestPlan("web", "simple", "курс доллара сегодня").search_query("Какой курс доллара сегодня?"),
                         "курс доллара сегодня")

    def test_compression_accepts_only_exact_source_quotes(self):
        selected = {"keep": [0]}
        with patch("intent_router.urllib.request.urlopen", return_value=response(selected)):
            result = IntentRouter({}).compress({"question": "Какая погода?", "sources": SOURCES})
        self.assertEqual(result[0]["text"], "Сейчас минус 5 градусов.")
        self.assertEqual(result[0]["url"], SOURCES[0]["url"])

    def test_hallucinated_compression_falls_back_to_original_facts(self):
        selected = {"facts": [{"source": 0, "quote": "Сейчас плюс 25 градусов."},
                              {"source": True, "quote": "Сейчас минус 5 градусов."}]}
        result = compact_sources("Какая погода?", SOURCES, selected)
        self.assertIn("минус 5", result[0]["text"])
        self.assertNotIn("плюс 25", str(result))

    def test_invalid_sentence_ids_never_select_unavailable_facts(self):
        result = compact_sources("Какая погода?", SOURCES, {"keep": [True, -1, 999]})
        self.assertTrue(result)
        self.assertTrue(all(item["text"] in SOURCES[0]["text"] for item in result))

    def test_compression_budget_is_bounded(self):
        sources = [dict(SOURCES[0], text=("Факт. " * 500)) for _ in range(4)]
        result = compact_sources("Факт", sources)
        self.assertLessEqual(sum(len(item["text"]) for item in result), 1800)


class ScriptedBankTests(unittest.TestCase):
    def test_every_action_has_ten_unique_variants_with_identical_parameters(self):
        formatter = string.Formatter()
        for key, variants in ACTION_REPLIES.items():
            self.assertEqual(len(variants), 10, key)
            self.assertEqual(len(set(variants)), 10, key)
            placeholders = [{field for _, field, _, _ in formatter.parse(text) if field} for text in variants]
            self.assertTrue(all(fields == placeholders[0] for fields in placeholders), key)
            self.assertEqual(persona.LINES[key], list(variants))

    def test_random_selection_reaches_all_ten_variants_and_keeps_volume(self):
        replies = []
        for index in range(10):
            with patch("persona.random.choice", side_effect=lambda values, i=index: values[i]):
                replies.append(persona.line("vol_set", n=37))
        self.assertEqual(len(set(replies)), 10)
        self.assertTrue(all("37" in reply for reply in replies))
