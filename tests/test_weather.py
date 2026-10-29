import datetime
import unittest
from unittest.mock import patch

import weather
from web_search import WebSearch


class WeatherTests(unittest.TestCase):
    def setUp(self):
        local = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=7)
        self.place = {"results": [{"name": "Краснообск", "latitude": 54.92, "longitude": 82.99}]}
        self.forecast = {"utc_offset_seconds": 25200,
                         "current": {"time": local.isoformat(), "temperature_2m": 3.2,
                                     "apparent_temperature": -1.1, "wind_speed_10m": 4.2, "weather_code": 3},
                         "daily": {"time": [local.date().isoformat(), (local.date() + datetime.timedelta(days=1)).isoformat()],
                                   "temperature_2m_min": [0, -2], "temperature_2m_max": [3, 1], "weather_code": [3, 71]}}

    def test_current_weather_preserves_location_units_and_signs(self):
        with patch.object(weather, "_get", side_effect=[self.place, self.forecast]) as get:
            result = weather.weather_sources("Какая погода в Краснообске?")[0]
        self.assertIn("name=%D0%BA%D1%80%D0%B0%D1%81%D0%BD%D0%BE%D0%BE%D0%B1%D1%81%D0%BA", get.call_args_list[0].args[0])
        self.assertIn("Краснообск", result["answer"])
        self.assertIn("плюс 3 градуса", result["answer"])
        self.assertIn("минус 1 градус", result["answer"])
        self.assertIn("4 метра в секунду", result["answer"])
        self.assertNotIn("open-meteo", result["answer"])

    def test_tomorrow_uses_next_day_not_current_conditions(self):
        with patch.object(weather, "_get", side_effect=[self.place, self.forecast]):
            result = weather.weather_sources("Погода завтра в Краснообске")[0]
        self.assertIn("завтра от -2 до 1", result["answer"])
        self.assertIn("снег", result["answer"])

    def test_stale_and_malformed_data_are_not_presented_as_weather(self):
        for field, value in (("time", "2000-01-01T00:00"), ("temperature_2m", float("nan"))):
            original = self.forecast["current"][field]
            self.forecast["current"][field] = value
            with patch.object(weather, "_get", side_effect=[self.place, self.forecast]):
                self.assertEqual(weather.weather_sources("Погода в Краснообске"), [])
            self.forecast["current"][field] = original

    def test_no_city_is_invented_and_basic_explanations_do_not_fetch(self):
        with patch.object(weather, "_get") as get:
            self.assertIn("Назови город", weather.weather_sources("Какая погода?")[0]["answer"])
            self.assertIsNone(weather.weather_sources("Почему погода меняется?"))
            self.assertIsNone(weather.weather_sources("Давай поговорим"))
            get.assert_not_called()

    def test_weather_avoids_search_snippets(self):
        sources = [{"title": "Weather", "url": "https://open-meteo.com/", "text": "Плюс 3 градуса.", "answer": "Плюс 3 градуса."}]
        with patch("web_search.weather_sources", return_value=sources), patch.object(WebSearch, "_fetch") as search:
            self.assertEqual(WebSearch().ask("Погода в Краснообске"), sources)
            search.assert_not_called()

    def test_generic_search_result_cannot_supply_a_ready_answer(self):
        row = {"href": "https://example.org/", "body": "Информация", "answer": "Выдуманный ответ"}
        with patch.object(WebSearch, "_fetch", return_value=[row]):
            result = WebSearch().ask("история Python")[0]
        self.assertNotIn("answer", result)
