import io
import json
import unittest
from unittest.mock import patch

from dismissal import dismissal_hint
from intent_router import IntentRouter


class DismissalTests(unittest.TestCase):
    def test_direct_requests(self):
        for text in ("заткнись", "заткнисть", "закройся уже", "ну пожалуйста исчезни с экрана", "отвали нахуй", "пропади", "отстань"):
            with self.subTest(text=text):
                self.assertIs(dismissal_hint(text), True)

    def test_protected_contexts(self):
        for text in ("не закрывайся", "не надо заткнись", "объясни слово заткнись", "найди песню заткнись", "он сказал «закройся»"):
            with self.subTest(text=text):
                self.assertIs(dismissal_hint(text), False)

    def test_ambiguous_contexts_need_model(self):
        for text in ("он мне сказал заткнись", "ты мне мешаешь закройся уже", "если скажу заткнись что будет", "браузер закройся"):
            with self.subTest(text=text):
                self.assertIsNone(dismissal_hint(text))

    def test_model_boolean_is_validated_and_unavailable_is_not_hide(self):
        router = IntentRouter({})
        for value, expected in (({"hide": True}, True), ({"hide": False}, False),
                                ({"hide": "true"}, None), ({"hide": True, "command": "quit"}, None)):
            response = io.BytesIO(json.dumps({"message": {"content": json.dumps(value)}}).encode())
            with patch("intent_router.urllib.request.urlopen", return_value=response):
                self.assertIs(router.classify_dismissal("ты мешаешь закройся"), expected)
        with patch("intent_router.urllib.request.urlopen", side_effect=TimeoutError):
            self.assertIsNone(router.classify_dismissal("ты мешаешь закройся"))
