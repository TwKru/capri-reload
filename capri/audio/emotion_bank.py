"""Reusable vocal reactions selected from recorded or pregenerated audio clips."""
import random
import re
from pathlib import Path

PREFIX = re.compile(r"^\s*(?:\[(хихикает|смеётся|вздыхает|возглас|удивляется|фыркает)\]|"
                    r"(хи[- ]хи(?:[- ]хи)*|хе[- ]хе|ха[- ]ха(?:[- ]ха)*)|"
                    r"(хмф|hmph|пф)(?=[!,.…\s]|$))\s*[!,.…]*\s*", re.I)
EVENTS = {"хихикает": "giggle", "смеётся": "laugh", "вздыхает": "sigh",
          "возглас": "exclaim", "удивляется": "gasp", "фыркает": "huff"}


class EmotionBank:
    def __init__(self, folder=None):
        self.root = Path(folder) if folder else None
        self.last = {}
        self.last_huff = float("-inf")

    def angry_prefix(self, text, now):
        if not self.root or not any((self.root / "huff").glob("*.wav")):
            return text
        if PREFIX.match(text) or now - self.last_huff < 20:
            return text
        self.last_huff = now
        return "Хмф! " + text

    def prefix(self, text):
        match = PREFIX.match(text)
        if not match or not self.root:
            return None, text
        if match.group(1):
            event = EVENTS[match.group(1).lower()]
        elif match.group(3):
            event = "huff"
        else:
            event = "laugh" if match.group(2).lower().startswith("ха") else "giggle"
        paths = list((self.root / event).glob("*.wav"))
        if not paths:
            return None, text
        choices = [p for p in paths if p != self.last.get(event)] or paths
        chosen = random.choice(choices)
        self.last[event] = chosen
        return chosen, text[match.end():]
