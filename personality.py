"""Локальное настроение персонажа: без моделей, таймеров и истории разговоров на диске."""
from dataclasses import dataclass

from action_replies import variants_for
import json
import math
import os
from pathlib import Path
import random
import re
import tempfile
import time


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower().replace("ё", "е"))).strip()


PATTERNS = tuple((event, re.compile(pattern)) for event, pattern in (
    ("greet", r"привет|приветик|здравствуй|здравствуйте|йоу|хай|ку"),
    ("talk", r"(?:ну |давай |может )?(?:поговорим|поболтаем)"),
    ("sorry", r"(?:ну )?(?:извини|извини меня|прости|прости меня|сорри|пардон|прошу прощения|"
              r"не обижайся|давай мириться|давай помиримся|мир|я не хотел тебя обидеть|я не хотела тебя обидеть)"),
    ("joke", r"(?:я )?(?:шучу|пошутил|пошутила|это шутка|это была шутка|это была всего лишь шутка)"),
    ("praise", r"(?:(?:ты|капри) (?:такая |очень |просто )?)?(?:умница|умничка|молодец|лучшая|"
               r"самая лучшая|красотка|красавица|классная|крутая|хорошая|супер|огонь)|"
               r"ты (?:все правильно сделала|здорово справилась|мне нравишься)"),
    ("thanks", r"(?:большое |огромное )?(?:спасибо|спс|пасиб|благодарю)(?: тебе| тебя| большое| капри)?"),
    ("hurt", r"(?:(?:ты|капри) чмо )?(?:да )?(?:пошла|иди)(?: ты)? (?:нахер|на хер|нахуй|на хуй|в пизду)"),
    ("hurt", r"(?:(?:ты|капри) (?:вообще |совсем |такая |просто |очень )?)?(?:тупая|глупая|дура|"
             r"дурочка|идиотка|бестолковая|бесполезная|тупица|сука|чмо)|ты (?:ничего не умеешь|меня бесишь)|"
             r"(?:да )?(?:пошла|иди)(?: ты)? (?:нафиг|нахуй|на хуй|в пизду)|обидься"),
    ("tease", r"(?:(?:ты|капри) (?:такая |просто )?)?(?:вредина|засранка|заноза|хитрюга)|не вредничай"),
    ("mood", r"(?:ну )?(?:как (?:у тебя )?настроение|какое у тебя настроение|как ты себя чувствуешь|как дела|как твои дела|"
             r"ты обиделась|ты на меня обиделась|ты злишься|ты на меня злишься|что с тобой|почему ты обиделась|на что ты обиделась)"),
    ("bored", r"(?:ты )?скучаешь|тебе скучно"),
    ("entertain", r"мне скучно|развесели меня|расскажи шутку|пошути"),
))

SEVERE_INSULT = re.compile(r"(?:(?:ты|капри) чмо )?(?:да )?(?:пошла|иди)(?: ты)? (?:нахер|на хер|нахуй|на хуй|в пизду)")
ANGRY_REPLIES = (
    "Ебать, у тебя манеры. Нести хуйню — не баг-репорт. Объясняй, что исправить.",
    "Нихуя себе общение. Посылать меня нахуй проще, чем нормально сформулировать задачу, да?",
    "Да поняла я, блядь. Теперь давай по делу, а не по этому пиздецу.",
)
ANGRY_MOOD_REPLIES = (
    "Обижена пиздец. После таких посылов я имею право побурчать. Но команды работают.",
    "Да, я злюсь, блядь. Не на задачу, а на то, как ты со мной разговариваешь.",
)
ANGRY_COMMAND_LINES = {
    "roam": "Ладно, блядь, пройдусь. Заодно остыну.",
    "wave": "Машу. Настроение пиздец, но жест работает.",
    "hide": "Уйду в тень. Если нужна помощь — объясни нормально, без этой хуйни.",
    "spin": "Ладно, блядь, один оборот. Злость мне крутиться не мешает.",
}
ANGRY_CONTEXT = (
    "Сильная обида после прямого посыла или повторных оскорблений пользователя. Только сейчас разрешён "
    "крепкий русский мат без звёздочек: блядь, нахуй, пиздец, охуел. Можно резко и саркастично ответить "
    "на грубость. Не угрожай, не затрагивай группы людей и не отказывай в помощи. Сначала отвечай по делу; "
    "короткий матерный подкол допустим. Это состояние закончится автоматически или после примирения."
)

REPLIES = {
    "greet": ("Привет! Я рядом.", "Привет. Как у тебя дела?"),
    "talk": ("Давай. Как у тебя день проходит?", "Я слушаю. Что у тебя на уме?"),
    "hurt": ("Эй, это было обидно. Немного побурчу, но с делами помогу.",
             "Ну спасибо. Я обиделась. Лучше скажи, что именно исправить.",
             "Колючая я, а не бронированная. Ладно, я тебя услышала."),
    "hurt_again": ("Я уже поняла. Давай лучше разберёмся, что не работает.",
                   "Ладно, подкол засчитан. А теперь скажи, что нужно сделать."),
    "sorry": ("Мир. Я уже оттаяла.", "Ладно, проехали. Снова на одной стороне.",
              "Извинения приняты. Долго дуться скучно."),
    "sorry_neutral": ("Всё нормально, я не сержусь.", "Да всё хорошо. Продолжаем."),
    "joke": ("Ага, подловил. Ладно, мир.", "Вот хитрость. Хорошо, шутка засчитана."),
    "praise": ("Вот теперь приятно. Постараюсь не зазнаться.", "Спасибо! Я сейчас очень довольная.",
               "Засчитано. Мои пиксели довольно улыбаются."),
    "thanks": ("Пожалуйста. Рада, что пригодилась.", "Обращайся. Люблю, когда всё получается.", "Всегда пожалуйста."),
    "thanks_hurt": ("Пожалуйста. Вот так уже приятнее.", "Обращайся. Я уже оттаиваю."),
    "tease": ("Вредина — это часть комплектации.", "Да, немного колючая. Зато со мной не скучно.",
              "Хитрая, быстрая, временами невыносимая. Всё по плану."),
    "bored": ("Чуть-чуть. Можешь отправить меня погулять или дать задачку.",
              "Есть немного. Пойду разомну пиксели, если попросишь."),
    "entertain": ("Если компьютер задумался, не мешай. Возможно, он тоже вспоминает, зачем открыл эту вкладку.",
                  "Мой план на день: помочь тебе и сделать вид, что всё было под контролем.",
                  "Судя по числу вкладок, твой браузер уже основал собственную цивилизацию."),
}

MOOD_REPLIES = {
    "neutral": ("Настроение ровное. Готова и поболтать, и помочь.", "Всё спокойно. Немного иронии в запасе."),
    "hurt": ("Немного обижена на грубость. Но команды выполняю как обычно.",
             "Ещё чуть-чуть дуюсь. Но уже остываю."),
    "happy": ("Хорошее! После добрых слов даже пиксели бодрее.", "Довольная. Сегодня у нас неплохая команда."),
    "playful": ("Озорное. Хочется немного подколоть и покрутиться.", "Настроение слегка вредное, но в хорошем смысле."),
    "bored": ("Немного скучаю. Дай задачку или отправь прогуляться.", "Тихо тут. Хочется какого-нибудь движения."),
}

MOOD_CONTEXT = {
    "neutral": "Сейчас настроение спокойное и дружелюбное. Не продолжай прежние обиды.",
    "hurt": "Игровое настроение Капри: слегка обижена на недавнюю грубость. Тон чуть суше и с лёгкой иронией. "
            "Не упрекай повторно, не отказывай в помощи и не искажай факты. Извинение сразу принимаешь.",
    "happy": "Игровое настроение Капри: довольна после похвалы. Тон тёплый, живой, чуть самоуверенный. Без лести.",
    "playful": "Игровое настроение Капри: озорное. Можно один добрый подкол, но сначала ответь по существу.",
    "bored": "Игровое настроение Капри: немного скучала, рада новой задаче. Отвечай живо, без жалоб и упрёков.",
}

COMMAND_LINES = {
    "hurt": {"roam": "Ладно, пройдусь. Заодно остыну.", "wave": "Помашу. Но я ещё чуть-чуть дуюсь.",
             "hide": "Ладно, уйду в тень. Если нужна помощь, позови.", "spin": "Ладно, один оборот. Даже обиженная я эффектная."},
    "happy": {"roam": "С удовольствием! Пойду разомну пиксели.", "wave": "Держи самый довольный привет!",
              "spin": "Смотри, какая я сегодня эффектная!"},
    "playful": {"roam": "Пойду патрулировать рабочий стол. Вкладки под подозрением.",
                "wave": "Машу! Только без автографов.", "spin": "Осторожно, демонстрация цифрового изящества!"},
    "bored": {"roam": "Наконец-то движение! Пойду прогуляюсь.", "wave": "Привет! Уже веселее."},
}


@dataclass(frozen=True)
class Reaction:
    command: str
    reply: str | None = None
    event: str | None = None


class Personality:
    def __init__(self, enabled=True, path=None, clock=None, persist=True):
        self.enabled = enabled
        self.clock = clock or time.time
        self.persist = persist
        self.path = Path(path) if path else Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Capri" / "personality.json"
        self._mood, self._until, self._strikes = "neutral", 0.0, 0
        self.last_interaction = self.clock()
        self._last_reply = {}
        if enabled and persist:
            self._load()

    def _load(self):
        try:
            if self.path.stat().st_size > 2048:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            mood, until, strikes = data.get("mood"), data.get("until"), data.get("strikes")
            now = self.clock()
            if (isinstance(mood, str) and mood in MOOD_CONTEXT and type(until) in (int, float) and math.isfinite(until) and
                    now < until <= now + 600 and type(strikes) is int and 0 <= strikes <= 3):
                self._mood, self._until, self._strikes = mood, until, strikes
        except (OSError, ValueError):
            pass

    def _save(self):
        if not self.persist:
            return
        staging = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, suffix=".tmp", delete=False) as file:
                staging = Path(file.name)
                json.dump({"mood": self._mood, "until": self._until, "strikes": self._strikes}, file)
            os.replace(staging, self.path)
        except OSError:
            pass
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass

    @property
    def mood(self):
        if not self.enabled:
            return "neutral"
        if self.clock() >= self._until:
            return "neutral"
        return self._mood

    def context(self):
        if not self.enabled:
            return ""
        if self.strongly_hurt:
            return MOOD_CONTEXT["hurt"] + "\n" + ANGRY_CONTEXT
        return MOOD_CONTEXT[self.mood] + "\nВ обычном ответе говори без мата. Крепкое междометие допустимо лишь изредка при сильной эмоции. Жёстких личных наездов сейчас не допускай."

    @property
    def strongly_hurt(self):
        return self.mood == "hurt" and self._strikes >= 3

    def command_line(self, key, default):
        if self.strongly_hurt:
            angry = ANGRY_COMMAND_LINES.get(key)
            return random.choice(variants_for(angry)) if angry else default
        text = COMMAND_LINES.get(self.mood, {}).get(key) if self.enabled else None
        return random.choice(variants_for(text)) if text else default

    def prewarm_phrases(self):
        if not self.enabled:
            return []
        phrases = [phrase for bank in (*REPLIES.values(), *MOOD_REPLIES.values()) for phrase in bank]
        phrases.extend(phrase for bank in COMMAND_LINES.values() for phrase in bank.values())
        phrases.extend((*ANGRY_REPLIES, *ANGRY_MOOD_REPLIES, *ANGRY_COMMAND_LINES.values()))
        return list(dict.fromkeys(phrases))

    @staticmethod
    def _event(text):
        value = clean(text)
        for event, pattern in PATTERNS:
            if pattern.fullmatch(value):
                return event
        return None

    @classmethod
    def can_handle(cls, text):
        return cls._event(text) is not None

    def _pick(self, key, choices):
        options = [value for value in choices if value != self._last_reply.get(key)] or choices
        reply = random.choice(options)
        self._last_reply[key] = reply
        return reply

    def _set(self, mood, duration):
        self._mood, self._until = mood, self.clock() + duration
        self._save()

    def react(self, text):
        if not self.enabled:
            return Reaction(text)
        previous = self.mood
        self.last_interaction = self.clock()
        event = self._event(text)
        event_text = text
        remainder = None
        if event is None:
            # Только отдельная социальная реплика в начале. Названия песен/поисковые запросы не трогаем.
            parts = re.split(r"[,;.!?]\s*", text, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                event = self._event(parts[0])
                event_text = parts[0]
                remainder = parts[1].strip() if event else None
        if event is None:
            return Reaction(text)
        key = event
        if event == "hurt":
            if SEVERE_INSULT.fullmatch(clean(event_text)):
                self._strikes = 3
            elif clean(event_text) == "обидься":
                self._strikes = self._strikes if previous == "hurt" else 1
            else:
                self._strikes = min(3, self._strikes + 1) if previous == "hurt" else 1
            self._set("hurt", 90 * self._strikes)
            key = "hurt_again" if self._strikes > 1 else "hurt"
        elif event in ("sorry", "joke"):
            self._strikes = 0
            self._set("playful" if event == "joke" else "neutral", 120 if event == "joke" else 0)
            if event == "sorry" and previous != "hurt":
                key = "sorry_neutral"
        elif event in ("praise", "thanks"):
            if event == "praise" or previous != "hurt":
                self._strikes = 0
                self._set("happy", 180)
            else:
                self._strikes = max(0, self._strikes - 1)
                self._set("hurt" if self._strikes else "neutral", 45 * self._strikes)
                key = "thanks_hurt"
        elif event == "tease":
            if previous != "hurt":
                self._set("playful", 120)
        elif event == "bored":
            if previous == "neutral":
                self._set("bored", 120)
        elif event == "entertain":
            self._strikes = 0
            self._set("playful", 120)
        if remainder:
            return Reaction(remainder, event=event)
        if event == "mood":
            if self.strongly_hurt:
                return Reaction(text, self._pick("angry_mood", ANGRY_MOOD_REPLIES), event)
            return Reaction(text, self._pick(self.mood, MOOD_REPLIES[self.mood]), event)
        if event == "hurt" and self.strongly_hurt:
            return Reaction(text, self._pick("angry", ANGRY_REPLIES), event)
        return Reaction(text, self._pick(key, REPLIES[key]), event)

    def chatter_line(self):
        if not self.enabled:
            return None
        if self.strongly_hurt:
            return self._pick("angry_chatter", ("Пойду прогуляюсь. Остыну от этого пиздеца.", "Ладно, блядь. Уже остываю, если нужна помощь — зови."))
        if self.mood == "neutral" and self.clock() - self.last_interaction > 900:
            self._set("bored", 120)
        choices = {
            "hurt": ("Пойду разомну пиксели. Бурчать на месте скучно.", "Уже остываю. Если нужна помощь, зови."),
            "happy": ("Что-то у меня сегодня всё получается. Подозрительно приятно.", "Настроение отличное. Самое время немного прогуляться."),
            "playful": ("Я тут. Делаю вид, что веду себя прилично.", "Серьёзное лицо не обещаю, помощь — обещаю."),
            "bored": ("Пойду разомну пиксели.", "Тихо тут. Можно прогуляться и придумать что-нибудь интересное."),
            "neutral": ("Я рядом, если понадоблюсь.", "Короткая прогулка по рабочему столу. И снова за дело.",
                        "Проверка связи. Всё спокойно.", "Интересно, сколько вкладок сегодня откроется?"),
        }
        return self._pick("chatter", choices[self.mood])
