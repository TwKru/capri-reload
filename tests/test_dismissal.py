import unittest

from dismissal import dismissal_hint


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
