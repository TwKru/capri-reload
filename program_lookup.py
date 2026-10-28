"""Расшифровка названий программ через интернет, без загрузки или запуска найденных файлов."""
from concurrent.futures import ThreadPoolExecutor
from itertools import product
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("capri")


def name_key(name):
    name = name.lower().replace("ё", "е").removesuffix(".exe")
    name = re.sub(r"\s+\((software|video game|application|program|компьютерная игра|программа|игра)\)$", "", name)
    roman = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
    name = re.sub(r"\b(ii|iii|iv|v|vi)\b", lambda m: roman[m.group()], name)
    name = re.sub(r"\s*[-–—]\s*steam$", "", name)
    return re.sub(r"[^a-zа-я0-9]", "", name)


def is_abbreviation(query):
    return bool(re.fullmatch(r"[\w .-]{1,40}", query) and 1 < len(name_key(query)) <= 14 and len(query.split()) <= 3)


def same_program(first, second):
    return bool(name_key(first) and name_key(first) == name_key(second))


def abbreviation_spellings(query):
    """Варианты записи букв: «кс2» ищется также как KS2 и CS2, без списка программ."""
    spellings = [query, query.upper(), query.title()]
    compact = re.sub(r"[ .-]", "", query.lower())
    letters = re.sub(r"\d", "", compact)
    if letters and len(letters) <= 4 and re.fullmatch(r"[а-я]+", letters):
        alphabet = dict(zip("абвгдеёжзийклмнопрстуфхцчшщыэюя",
                            ("a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "kc", "l", "m",
                             "n", "o", "p", "r", "sc", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "y", "e", "yu", "ya")))
        variants = [""]
        for char in compact:
            value = alphabet.get(char, char)
            options = tuple(value) if char in "кс" else (value,)
            variants = [prefix + suffix for prefix, suffix in product(variants, options)][:16]
        spellings.extend(value.upper() for value in variants)
    return list(dict.fromkeys(spellings))


def steam_games(roots=None):
    """Названия установленных Steam-игр из локальных манифестов, даже без ярлыка в «Пуске»."""
    if roots is None:
        import winreg
        roots = []
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                continue
    libraries = {Path(root) for root in roots}
    for root in list(libraries):
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8-sig")
            for path in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"', text):
                libraries.add(Path(path.replace("\\\\", "\\").replace('\\"', '"')))
        except OSError:
            continue
    games = {}
    for library in libraries:
        for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
            try:
                fields = dict(re.findall(r'"(appid|name|installdir)"\s*"([^"\r\n]+)"',
                                         manifest.read_text(encoding="utf-8-sig")))
                app_id, name = fields.get("appid", ""), fields.get("name", "")
                folder = (library / "steamapps" / "common" / fields.get("installdir", "")).resolve()
                common = (library / "steamapps" / "common").resolve()
                if (re.fullmatch(r"\d{1,12}", app_id) and name and fields.get("installdir") and
                        folder.is_relative_to(common) and folder.is_dir()):
                    games[name] = "steam://rungameid/" + app_id
            except (OSError, ValueError):
                continue
    return list(games.items())


class AmbiguousProgram(ValueError):
    def __init__(self, names):
        self.names = sorted(set(names))
        super().__init__(", ".join(self.names))


class ProgramLookup:
    def __init__(self, timeout=3.5, cache_path=None):
        self.timeout = timeout
        self.cache_path = Path(cache_path) if cache_path else Path(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Capri" / "program_names.json"
        self.cache = None
        self.lock = threading.Lock()

    def _load(self):
        if self.cache is not None:
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.cache = {}

    def _save(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_path.parent,
                                             suffix=".tmp", delete=False) as file:
                staging = Path(file.name)
                json.dump(self.cache, file, ensure_ascii=False)
            try:
                os.replace(staging, self.cache_path)
            finally:
                staging.unlink(missing_ok=True)
        except OSError:
            log.info("Не удалось сохранить найденные названия программ")

    def _request(self, language, params):
        url = f"https://{language}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "format": "json", "formatversion": 2, **params})
        request = urllib.request.Request(url, headers={
            "User-Agent": "CapriReload/1.0 (+https://github.com/TwKru/capri-reload)"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read(512 * 1024))

    @staticmethod
    def _titles(data):
        names = []
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            if "disambiguation" in page.get("pageprops", {}):
                names.extend(link.get("title", "") for link in page.get("links", []))
            else:
                names.append(page.get("title", ""))
        # Результаты используются только для сравнения с локальными именами, не как команды или пути.
        return [name for name in names if isinstance(name, str) and 1 < len(name) <= 120 and
                not any(char in name for char in ("\n", "\r", "\x00", "\\", "/"))]

    def _lookup_language(self, language, query):
        try:
            data = self._request(language, {"action": "query", "titles": "|".join(abbreviation_spellings(query)), "redirects": 1,
                "prop": "links|pageprops", "pllimit": 30, "plnamespace": 0})
            names = self._titles(data)
            if names:
                return names
            # Поиск нужен, если у сокращения нет собственной статьи или перенаправления.
            data = self._request(language, {"action": "query", "generator": "search",
                "gsrsearch": query, "gsrlimit": 4, "gsrnamespace": 0,
                "prop": "links|pageprops", "pllimit": 20, "plnamespace": 0})
            return self._titles(data)
        except Exception as error:
            log.info("Поиск названия %s (%s) недоступен: %s", query, language, error)
            return []

    def resolve(self, query):
        query = re.sub(r"\s+", " ", query.strip())
        if not is_abbreviation(query):
            return []
        key = name_key(query)
        with self.lock:
            self._load()
            cached = self.cache.get(key)
            if isinstance(cached, dict) and isinstance(cached.get("until"), (int, float)):
                names = cached.get("names")
                if cached["until"] > time.time() and isinstance(names, list) and all(isinstance(n, str) for n in names):
                    return names[:40]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda lang: self._lookup_language(lang, query), ("en", "ru")))
        names = list(dict.fromkeys(name for result in results for name in result))[:40]
        with self.lock:
            self.cache[key] = {"names": names, "until": time.time() + (7 * 86400 if names else 300)}
            self._save()
        log.info("Интернет-поиск %s: %s названий", query, len(names))
        return names
