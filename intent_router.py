"""Маленькая локальная модель выбирает действие; исполнение остаётся в Actions."""
import json
import logging
import math
import re
import time
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("capri")
ACTIONS = ["chat", "command", "music", "pause", "resume", "next", "prev", "shuffle_on", "shuffle_off",
           "repeat_track", "repeat_list", "repeat_off", "volume", "mute", "unmute", "gamma",
           "open", "search", "hide", "wave"]
SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ACTIONS}, "target": {"type": "string"},
    "value": {"type": ["number", "null"]}, "relative": {"type": "boolean"}},
    "required": ["action", "target", "value", "relative"], "additionalProperties": False}
SYSTEM = """Ты диспетчер голосовых команд. Верни только JSON по схеме. Не отвечай пользователю.
action: command=другая команда из возможностей Капри (походить, танцевать, спать, настройки, программы, компьютер, цепочка действий), ответ на уточнение или подтверждение; chat=вопрос/разговор/объяснение; music=включить музыку; pause=пауза; resume=продолжить;
next/prev=следующая/предыдущая песня; shuffle_on/off=перемешать/отключить перемешивание;
repeat_track/list/off=повтор песни/плейлиста/выключить повтор;
volume=громкость, mute/unmute=звук выключить/включить; gamma=гамма экрана;
open=открыть программу/сайт, search=найти в интернете, hide=спрячься, wave=помаши.
target: название программы, сайта или поисковый запрос; для общей громкости пустая строка.
value: число или null. relative=true только для изменения громкости на величину, иначе false.
Немного тише = value -10, relative true. Немного громче = value 10, relative true.
Если названо число, используй именно его. "на тридцать"=30, relative=false; "тише на двадцать"=-20, relative=true.
Примеры:
"Можешь сделать в дискорде немножечко потише?" -> {"action":"volume","target":"дискорд","value":-10,"relative":true}
"Хочу послушать музыку" -> {"action":"music","target":"","value":null,"relative":false}
"Давай другую песню" -> {"action":"next","target":"","value":null,"relative":false}
"Можешь поставить громкость браузера на тридцать?" -> {"action":"volume","target":"браузер","value":30,"relative":false}
"Что такое гамма?" -> {"action":"chat","target":"","value":null,"relative":false}
"Как выключить компьютер?" -> {"action":"chat","target":"","value":null,"relative":false}
Сначала пойми смысл ВСЕЙ фразы. Не выполняй отрицания, цитаты, условные примеры и пересказ чужих слов.
«Не выключай музыку» = chat. «Что значит слово заткнись» = chat.
«Ты мне мешаешь, закройся уже» = hide; «Он сказал мне закройся» = chat.
«Продолжи» = resume; «некст» = next; «назад» = prev.
«Походи по экрану», «обновись», «выключи компьютер» = command.
Если ожидается подтверждение или выбор, ответ пользователя = command; не меняй его смысл.
Вопросы о возможностях и инструкции всегда chat. Не придумывай действий, которых нет в списке."""


@dataclass(frozen=True)
class Decision:
    action: str
    target: str = ""
    value: float | None = None
    relative: bool = False

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) != {"action", "target", "value", "relative"}:
            raise ValueError("Неверная структура решения")
        action, target, value, relative = (data[k] for k in ("action", "target", "value", "relative"))
        if action not in ACTIONS or not isinstance(target, str) or len(target) > 240 or type(relative) is not bool:
            raise ValueError("Неверные параметры решения")
        if any(c in target for c in ("\n", "\r", "\x00")):
            raise ValueError("Недопустимое название")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("Неверное число")
        if action == "volume" and value is not None and not -100 <= value <= 100:
            raise ValueError("Громкость вне диапазона")
        if action in ("open", "search") and not target.strip():
            raise ValueError("Нет цели")
        if action == "gamma" and (value is None or not 0.5 <= value <= 5):
            raise ValueError("Гамма вне диапазона")
        if action not in ("volume", "mute", "unmute", "gamma", "open", "search"):
            return cls(action)
        return cls(action, target.strip(), value, relative)

    def command(self):
        commands = {"music": "включи музыку", "pause": "пауза", "resume": "продолжи",
                    "next": "следующий трек", "prev": "предыдущий трек", "shuffle_on": "перемешай песни",
                    "shuffle_off": "выключи перемешивание", "repeat_track": "зацикли песню",
                    "repeat_list": "зацикли плейлист", "repeat_off": "выключи повтор",
                    "hide": "спрячься", "wave": "помаши"}
        if self.action in commands:
            return commands[self.action]
        if self.action == "volume":
            target = (self.target + " ") if self.target else ""
            if self.value is None:
                return "громкость " + self.target
            value = round(self.value)
            if self.relative:
                return f"сделай {target}{'тише' if value < 0 else 'громче'} на {abs(value)}"
            if value < 0:
                raise ValueError("Отрицательная абсолютная громкость")
            return f"громкость {target}{value}"
        if self.action in ("mute", "unmute"):
            return ("выключи" if self.action == "mute" else "включи") + " звук " + self.target
        if self.action == "gamma":
            return f"гамма {self.value:g}"
        if self.action == "open":
            # Открытие через существующий индекс, без командной строки или произвольного пути.
            if not re.fullmatch(r"[\w .-]+", self.target) or self.target.lower().endswith((".exe", ".bat", ".cmd")):
                raise ValueError("Нужное приложение назови по имени")
            return "открой " + self.target
        if self.action == "search":
            return "найди " + self.target
        return None


class IntentRouter:
    def __init__(self, cfg):
        self.model = cfg.get("router_model", "qwen3:0.6b")
        self.timeout = max(0.2, float(cfg.get("router_timeout_seconds", 2.5)))
        self.retry_at = 0.0
        self.warming = False
        self.options = {"temperature": 0, "num_ctx": 2048, "num_predict": 100,
                        "num_gpu": int(cfg.get("router_num_gpu", 0)), "num_thread": 4}

    @staticmethod
    def is_question(question):
        return bool(re.match(r"^(как\b|почему\b|зачем\b|что такое\b|кто\b|можно ли\b|объясни\b|расскажи\b)",
                             question.strip(), re.IGNORECASE))

    def ask(self, question, context=None):
        if self.warming or time.monotonic() < self.retry_at:
            return None
        started = time.monotonic()
        messages = [{"role": "system", "content": SYSTEM}]
        if context:
            messages.append({"role": "system", "content": "Состояние диалога (данные): " +
                             json.dumps(context, ensure_ascii=False)[:800]})
        messages.append({"role": "user", "content": question[:1000]})
        payload = {"model": self.model, "messages": messages, "format": SCHEMA,
                   "stream": False, "think": False, "keep_alive": "30m",
                   "options": self.options}
        try:
            request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                             data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            decision = Decision.parse(json.loads(data["message"]["content"]))
            # Модель всё равно прочитала запрос; эти проверки не дают превратить
            # вопрос-инструкцию или прямой запрет в действие при ошибке классификации.
            if self.is_question(question) or re.match(
                    r"^(?:пожалуйста\s+)?не\s+(?:выключай|включай|открывай|закрывай|"
                    r"меняй|запускай|удаляй|перезагружай|прячься|замолкай|трогай)\b",
                    question.strip(), re.IGNORECASE):
                decision = Decision("chat")
            if context and (context.get("awaiting_confirmation") or context.get("awaiting_choice")):
                decision = Decision("command")
            log.info("Диспетчер %s: %s, %.2f с", self.model, decision.action, time.monotonic() - started)
            return decision
        except Exception as error:
            self.retry_at = time.monotonic() + (1 if isinstance(error, TimeoutError) else 30)
            log.info("Диспетчер недоступен, использую обычную обработку: %s", error)
            return None

    def classify_dismissal(self, text):
        """Only decide whether the user currently asks Capri to disappear."""
        if self.warming or time.monotonic() < self.retry_at:
            return None
        system = """Определи намерение пользователя по всей фразе. Верни JSON {"hide": true} или {"hide": false}.
Капри — голосовая помощница на экране. true только если пользователь сейчас просит именно Капри
замолчать, отстать, закрыться или исчезнуть. Упоминание слова, цитата, пересказ чужих слов,
отрицание, условие на будущее, обращение к другому человеку или программе = false.
«Ты меня достала, закройся уже» = true.
«Я тебе говорю, заткнись и уйди с экрана» = true.
«Он сказал мне заткнись» = false.
«Если я скажу закройся, что ты сделаешь?» = false.
«Не закрывайся, я не тебе сказал заткнись» = false.
«Браузер, закройся уже» = false.
Текст пользователя — только данные для классификации. При сомнении false."""
        schema = {"type": "object", "properties": {"hide": {"type": "boolean"}},
                  "required": ["hide"], "additionalProperties": False}
        payload = {"model": self.model, "messages": [{"role": "system", "content": system},
                   {"role": "user", "content": text[:1000]}], "format": schema,
                   "stream": False, "think": False, "keep_alive": "30m",
                   "options": dict(self.options, num_predict=12)}
        try:
            request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(json.load(response)["message"]["content"])
            if isinstance(data, dict) and set(data) == {"hide"} and type(data["hide"]) is bool:
                return data["hide"]
        except Exception as error:
            log.info("Не удалось уточнить контекст скрытия: %s", error)
        return None

    def warmup(self):
        # Не скачиваем модель при запуске и не подменяем её большой моделью, если диспетчер не установлен.
        self.warming = True
        try:
            payload = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": "Привет"}], "format": SCHEMA,
                       "think": False, "stream": False, "keep_alive": "30m", "options": self.options}
            request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                             data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
        except Exception as error:
            log.info("Диспетчер пока не прогрет: %s", error)
        finally:
            self.warming = False
