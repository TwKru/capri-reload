"""Текущая погода и прогноз на завтра: числовые данные вместо поисковых описаний."""
import datetime
import json
import logging
import math
import re
import urllib.parse
import urllib.request

log = logging.getLogger("capri")
CONDITIONS = {0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
              45: "туман", 48: "туман", 51: "слабая морось", 53: "морось", 55: "сильная морось",
              56: "ледяная морось", 57: "ледяная морось", 61: "небольшой дождь", 63: "дождь",
              65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег",
              73: "снег", 75: "сильный снег", 77: "снежная крупа", 80: "ливневый дождь",
              81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад",
              95: "гроза", 96: "гроза с градом", 99: "гроза с градом"}


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "CapriReload/1.0"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read(300000))


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Некорректные данные погоды")
    return round(value)


def _unit(value, forms):
    count = abs(value)
    form = forms[2] if 11 <= count % 100 <= 14 else forms[0] if count % 10 == 1 else forms[1] if 2 <= count % 10 <= 4 else forms[2]
    return f"{value} {form}"


def _temperature(value):
    prefix = "плюс " if value > 0 else "минус " if value < 0 else ""
    return prefix + _unit(abs(value), ("градус", "градуса", "градусов"))


def location_candidates(query):
    text = query.lower()
    after_weather = re.split(r"\bпогод\w*", text, maxsplit=1)
    if len(after_weather) == 2 and re.search(r"\b(?:в|во)\s", after_weather[1]):
        text = after_weather[1]
    match = re.search(r"\b(?:в|во)\s+(?:городе\s+)?([а-яёa-z][а-яёa-z -]{1,70})", text)
    if not match:
        return []
    city = re.split(r"\b(?:сегодня|завтра|сейчас|на|утром|вечером|ночью|пожалуйста)\b", match[1])[0].strip()
    if not city:
        return []
    known = {"москве": "москва", "санкт-петербурге": "санкт-петербург", "петербурге": "санкт-петербург"}
    candidates = [known.get(city, city)]
    if city.endswith("е") and city not in known:
        candidates = [city[:-1], city, city[:-1] + "а"]
    qualifier = re.search(r",\s*([а-яёa-z][а-яёa-z -]{1,60})", text)
    if qualifier:
        region = re.split(r"\b(?:сегодня|завтра|сейчас|на|пожалуйста)\b", qualifier[1])[0].strip()
        candidates = [candidate + ", " + region for candidate in candidates]
    return list(dict.fromkeys(candidates))


def weather_sources(query):
    if not re.search(r"\bпогод[ауы]|\bпрогноз погод", query.lower()):
        return None
    # Историю, объяснения и отдалённые даты оставляем обычному информационному поиску.
    if re.search(r"почему|что такое|истори|недел|месяц|послезавтра|вчера|марс", query.lower()):
        return None
    candidates = location_candidates(query)
    if not candidates:
        return [{"title": "Уточнение города", "url": "https://open-meteo.com/", "text": "Город не указан.",
                 "answer": "Назови город в запросе, например: погода в Краснообске."}]
    try:
        place = None
        for name in candidates:
            geo = _get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
                {"name": name, "count": 3, "language": "ru", "format": "json"}))
            matches = geo.get("results", [])
            exact = [item for item in matches if item.get("name", "").casefold() == name.split(",", 1)[0].strip().casefold()]
            if len(exact) == 1:
                place = exact[0]
                break
        if place is None:
            return [{"title": "Уточнение города", "url": "https://open-meteo.com/", "text": "Город не определён однозначно.",
                     "answer": "Не смогла однозначно определить город. Уточни город и область в запросе о погоде."}]
        lat = place["latitude"]
        lon = place["longitude"]
        _number(lat, -90, 90)
        _number(lon, -180, 180)
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "timezone": "auto", "wind_speed_unit": "ms", "forecast_days": 2,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_min,temperature_2m_max,weather_code"})
        data = _get(url)
        current = data["current"]
        observed = datetime.datetime.fromisoformat(current["time"])
        local_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(
            seconds=data["utc_offset_seconds"])
        if abs((local_now - observed).total_seconds()) > 10800:
            raise ValueError("Устаревшие данные погоды")
        name = place["name"]
        if re.search(r"\bзавтра\b", query.lower()):
            daily = data["daily"]
            expected = (local_now.date() + datetime.timedelta(days=1)).isoformat()
            if daily["time"][1] != expected:
                raise ValueError("Дата прогноза не совпадает")
            low = _number(daily["temperature_2m_min"][1], -100, 70)
            high = _number(daily["temperature_2m_max"][1], -100, 70)
            condition = CONDITIONS.get(daily["weather_code"][1], "")
            answer = f"{name}: завтра от {low} до {high} градусов." + (f" {condition.capitalize()}." if condition else "")
        else:
            temp = _number(current["temperature_2m"], -100, 70)
            feels = _number(current["apparent_temperature"], -120, 90)
            wind = _number(current["wind_speed_10m"], 0, 150)
            condition = CONDITIONS.get(current["weather_code"], "")
            answer = (f"{name}: сейчас {_temperature(temp)}" + (f", {condition}" if condition else "") +
                      f". Ощущается как {_temperature(feels)}. Ветер {_unit(wind, ('метр', 'метра', 'метров'))} в секунду.")
        return [{"title": "Open-Meteo — погода, CC BY 4.0", "url": url, "text": answer, "answer": answer}]
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        log.info("Не удалось получить точную погоду: %s", error)
        return []
