"""Bounded local checks before asking the small model about dismissal context."""
import re

CANDIDATE = re.compile(r"\b(?:заткни(?:сь|сть)|закройся|закрывайся|замолкай|исчезай|прячься|скрывайся|уходи|замолчи|помолчи|молчи|умолкни|отвали|исчезни|спрячься|скройся|уйди|убирайся|свали)\b", re.I)


def dismissal_hint(text):
    """True = direct request, False = protected mention, None = needs context model."""
    text = text.lower().replace("ё", "е").strip()
    if not CANDIDATE.search(text):
        return False
    # Negation and explicitly quoted/educational uses must never trigger an action.
    if re.search(r"\bне\s+(?:надо\s+|нужно\s+|смей\s+)?" + CANDIDATE.pattern, text):
        return False
    if re.search(r"[«\"].*" + CANDIDATE.pattern + r".*[»\"]", text):
        return False
    if re.search(r"\b(?:слово|слова|фраза|фразу|фразы|означает|значит|переведи|найди|поищи|объясни|расскажи)\b", text):
        return False
    fillers = r"(?:ну|да|уже|просто|пожалуйста|лучше|давай|ты|капри|нахуй|на\s+хуй|блядь|блять)"
    direct = rf"(?:{fillers}[\s,!.?]*)*{CANDIDATE.pattern}(?:[\s,!.?]*(?:{fillers}|с\s+экрана|с\s+монитора|на\s+время))*[\s,!.?]*"
    return True if re.fullmatch(direct, text) else None
