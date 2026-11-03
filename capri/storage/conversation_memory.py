"""Локальная память: факты пользователя и ограниченная история, без вызовов ИИ."""
import copy
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("capri")
MAX_FACTS, MAX_TURNS = 100, 100
PERSONAL = (
    ("name", r"(?:меня зовут|мо[её] имя)\b"),
    ("home", r"я (?:живу|проживаю)\b"),
    ("work", r"я работаю\b"),
    ("study", r"я учусь\b"),
    ("preference", r"(?:мне нравится|я люблю|я предпочитаю|мой любимый|моя любимая)\b"),
)
SECRET = re.compile(r"sk-[\w-]{10,}|AIza[\w-]{20,}|\b(?:api[_ -]?key|api[_ -]?ключ|пароль|password)\b", re.I)


def normalized(text):
    return re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip(" .!?;:")


def fact_key(text):
    for key, pattern in PERSONAL:
        if re.match(pattern, text, re.I) and key != "preference":
            return key
    return normalized(text)


class MemoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {"version": 1, "facts": [], "dialogue": []}
        self.error = None
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict) or data.get("version") != 1:
                    raise ValueError("Неверная версия памяти")
                facts, dialogue = data.get("facts"), data.get("dialogue")
                if not isinstance(facts, list) or not isinstance(dialogue, list):
                    raise ValueError("Неверная структура памяти")
                if any(not isinstance(f, dict) or not isinstance(f.get("text"), str) or
                       not isinstance(f.get("key"), str) for f in facts):
                    raise ValueError("Неверные факты")
                if any(not isinstance(t, dict) or not isinstance(t.get("question"), str) or
                       not isinstance(t.get("answer"), str) for t in dialogue):
                    raise ValueError("Неверная история")
                self.data = {"version": 1, "facts": [{"key": f["key"][:400], "text": f["text"][:400]}
                    for f in facts[-MAX_FACTS:] if not SECRET.search(f["text"])],
                    "dialogue": [{"question": t["question"][:700], "answer": t["answer"][:900], "at": t.get("at", time.time())}
                    for t in dialogue[-MAX_TURNS:] if not SECRET.search(t["question"] + t["answer"]) and isinstance(t.get("at",0),(int,float)) and t.get("at",time.time()) >= time.time()-7*86400]}
                if data != self.data:
                    self._commit(self.data)
            else:
                self._commit(self.data)
        except (OSError, ValueError):
            self.error = "Не удалось прочитать или записать memory.json. Проверь файл и права доступа."
            log.warning("Локальная память недоступна; исходный файл сохранён")

    def _commit(self, data, reset=False):
        if self.error and not reset:
            raise ValueError(self.error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".capri-memory-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.data = data
        self.error = None

    def remember(self, text):
        text = re.sub(r"\s+", " ", text).strip()[:400]
        if not text:
            return "Что именно запомнить?"
        if SECRET.search(text):
            return "Ключи и пароли в память не записываю."
        with self.lock:
            data = copy.deepcopy(self.data)
            key = fact_key(text)
            previous = [f for f in data["facts"] if f["key"] == key]
            if previous and normalized(previous[-1]["text"]) == normalized(text):
                return "Я это уже помню."
            data["facts"] = [f for f in data["facts"] if f["key"] != key]
            data["facts"].append({"key": key, "text": text})
            data["facts"] = data["facts"][-MAX_FACTS:]
            # После исправления личного факта старый вариант не возвращается из истории.
            if previous:
                old = [normalized(f["text"]) for f in previous]
                data["dialogue"] = [t for t in data["dialogue"]
                    if not any(value in normalized(t["question"] + " " + t["answer"]) for value in old)]
            self._commit(data)
            self._sync_notes()
        return "Запомнила: " + text

    def _sync_notes(self, forget=None):
        """Факты в me.md; рукописные заметки вне управляемого блока сохраняются."""
        path = self.path.with_name("me.md")
        try:
            notes = path.read_text(encoding="utf-8-sig") if path.exists() else "# Заметки обо мне\n\n"
            notes = re.sub(r"\n?<!-- capri:facts -->.*?<!-- /capri:facts -->\n?", "\n", notes, flags=re.S)
            removed_manual = bool(forget and any(forget in normalized(row) for row in notes.splitlines()))
            if forget:
                notes = "\n".join(row for row in notes.splitlines() if forget not in normalized(row))+"\n"
            block = "\n<!-- capri:facts -->\n"+"\n".join("- "+fact["text"] for fact in self.data["facts"])+"\n<!-- /capri:facts -->\n"
            descriptor, temporary = tempfile.mkstemp(prefix=".capri-notes-",suffix=".tmp",dir=path.parent)
            try:
                with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
                    stream.write(notes.rstrip()+"\n"+block)
                os.replace(temporary,path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return removed_manual
        except (OSError,UnicodeError):
            log.warning("Факт сохранён в memory.json; не удалось синхронизировать me.md")
            return False

    def observe(self, question):
        if len(question) <= 400 and not any(mark in question for mark in ('?', '«', '»', '"', '\n')):
            if any(re.match(pattern, question, re.I) for _, pattern in PERSONAL):
                return self.remember(question).startswith("Запомнила:")
        return False

    def record(self, question, answer):
        if SECRET.search(question + answer):
            return
        with self.lock:
            data = copy.deepcopy(self.data)
            data["dialogue"].append({"question": question[:700], "answer": answer[:900], "at": time.time()})
            data["dialogue"] = [t for t in data["dialogue"][-MAX_TURNS:] if t.get("at",time.time()) >= time.time()-7*86400]
            self._commit(data)

    def forget(self, query):
        query = normalized(query)
        if not query:
            return "Какой факт забыть?"
        with self.lock:
            data = copy.deepcopy(self.data)
            facts = [f for f in data["facts"] if query in normalized(f["text"])]
            data["facts"] = [f for f in data["facts"] if f not in facts]
            data["dialogue"] = [t for t in data["dialogue"] if query not in normalized(t["question"] + " " + t["answer"])]
            removed = data != self.data
            if removed:
                self._commit(data)
            removed = self._sync_notes(forget=query) or removed
        return "Забыла." if removed else "Такой записи в памяти нет."

    def clear(self):
        with self.lock:
            self._commit({"version": 1, "facts": [], "dialogue": []}, reset=True)
            notes = self.path.with_name("me.md")
            if notes.exists():
                notes.write_text("# Заметки обо мне\n\n",encoding="utf-8")
        return "Память очищена."

    def prune(self):
        with self.lock:
            fresh = [turn for turn in self.data["dialogue"] if turn.get("at",time.time()) >= time.time()-7*86400]
            if len(fresh) != len(self.data["dialogue"]):
                data = copy.deepcopy(self.data)
                data["dialogue"] = fresh
                self._commit(data)

    def recent(self):
        self.prune()
        with self.lock:
            if not self.data["dialogue"]:
                return []
            turn = self.data["dialogue"][-1]
            return [{"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": turn["answer"]}]

    def context(self, question, budget=900):
        self.prune()
        terms = {word[:5] for word in re.findall(r"\w{4,}", normalized(question))}
        def score(text):
            return len(terms & {word[:5] for word in re.findall(r"\w{4,}", normalized(text))})
        with self.lock:
            facts = sorted(reversed(self.data["facts"]), key=lambda f: -score(f["text"]))
            rows = [f["text"] for f in facts if score(f["text"]) or f["key"] in ("name", "home", "work", "study")]
            turns = sorted(reversed(self.data["dialogue"][:-1]), key=lambda t: -score(t["question"]))
            try:
                notes = self.path.with_name("me.md").read_text(encoding="utf-8-sig")[:8000]
                notes = re.sub(r"<!-- capri:facts -->.*?<!-- /capri:facts -->", "", notes, flags=re.S)
                rows += [row.strip(" -\t") for row in notes.splitlines() if row.strip() and not row.startswith("#") and not SECRET.search(row)]
            except (OSError, UnicodeError):
                pass
            rows += [t["question"] + " → " + t["answer"] for t in turns if score(t["question"])]
            chosen, size, seen = [], 0, set()
            for text in rows:
                if normalized(text) not in seen and size + len(text) + 1 <= budget:
                    chosen.append(text)
                    seen.add(normalized(text))
                    size += len(text) + 1
        return "\n".join(chosen)

    def command(self, question):
        text = question.strip()
        if re.fullmatch(r"(?:что ты (?:обо мне )?помнишь|покажи память|что (?:у тебя )?в памяти)[?.!]*", text, re.I):
            with self.lock:
                if self.error:
                    return self.error
                rows = [f["text"] for f in self.data["facts"][-8:]]
                return "Помню: " + "; ".join(rows) if rows else "Сохранённых фактов пока нет."
        if re.fullmatch(r"(?:очисти|сбрось) (?:всю |свою )?память[.!]*", text, re.I):
            return self.clear()
        forget = re.match(r"^(?:забудь факт|забудь из памяти|удали из памяти)\s*[: ,]?\s+(.+)$", text, re.I)
        if forget:
            return self.forget(forget.group(1))
        remember = re.match(r"^запомни(?:\s+(?:мне|себе))?\s*[:,]?\s+(.+)$", text, re.I)
        if remember:
            fact = re.sub(r"^что\s+", "", remember.group(1), flags=re.I)
            # Существующие команды сохранения сайта, приложения и ответа остаются в Actions.
            if re.match(r"(?:(?:этот|эту|это|текущ\w+|открыт\w+)\s+)?"
                        r"(?:сайт|страниц|вкладк|ссылк|программ|приложени|игр|ответ)\w*\b", fact, re.I):
                return None
            return self.remember(fact)
        return None
