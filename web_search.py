"""Фоновый поиск: только текущий запрос, без открытия окон и передачи истории."""
import html
import ipaddress
import logging
import re
import threading
import time
from urllib.parse import urlsplit

log = logging.getLogger("capri")


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    value = html.unescape(re.sub(r"<[^>]*>", " ", value))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def valid_url(value):
    if not isinstance(value, str) or len(value) > 1500 or any(ord(c) < 32 for c in value):
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if url.scheme not in ("https", "http") or not host or url.username or url.password:
            return False
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class WebSearch:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    @staticmethod
    def _fetch(query):
        from ddgs import DDGS
        return DDGS(timeout=4).text(query, region="ru-ru", max_results=4,
                                   backend="google,brave,bing,duckduckgo")

    def ask(self, question):
        query = _text(question, 500)
        if not query:
            return []
        with self.lock:
            cached = self.cache.get(query)
            if cached and time.monotonic() - cached[0] < 120:
                return [dict(item) for item in cached[1]]
        try:
            rows = self._fetch(query)
        except Exception as error:
            log.info("Фоновый поиск недоступен: %s", error)
            return []
        sources, seen = [], set()
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            url = row.get("href")
            body = _text(row.get("body"), 700)
            if not valid_url(url) or not body or url in seen:
                continue
            seen.add(url)
            sources.append({"title": _text(row.get("title"), 180), "url": url, "text": body})
            if len(sources) == 4:
                break
        if sources:
            with self.lock:
                if len(self.cache) >= 24:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[query] = (time.monotonic(), sources)
            log.info("Фоновый поиск: найдено источников %d", len(sources))
        return [dict(item) for item in sources]


def source_excerpt(sources):
    """Запасной пересказ найденного фрагмента, когда разговорная модель недоступна."""
    first = sources[0]
    host = urlsplit(first["url"]).hostname
    text = first["text"][:500]
    return f"Вот фрагмент из найденного источника {host}: {text}"
