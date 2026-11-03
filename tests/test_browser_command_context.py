import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from capri.automation.command_dispatcher import Actions


class BrowserCommandContextTests(unittest.TestCase):
    def setUp(self):
        with patch("capri.automation.command_dispatcher.AppIndex.build"):
            self.actions = Actions({},".",None)
        self.actions.web = Mock()

    def test_logged_infinitive_search_and_inverted_followup_open_previous_topic(self):
        reply = self.actions.handle("найти cyberpunk 2077 edge riders")
        self.assertEqual(reply.action,"research")
        self.actions.web.assert_not_called()
        with patch.object(self.actions,"run_chain") as chain:
            reply = self.actions.handle("в браузере мне его открой")
        chain.assert_not_called()
        self.assertNotEqual(reply.action,"research")
        url = self.actions.web.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(url).query)["q"],["cyberpunk 2077 edge riders"])

    def test_explicit_browser_targets_are_not_split_or_sent_to_ai(self):
        for phrase in ("найди котов в браузере","открой в браузере котов","в браузере котов открой"):
            self.actions.web.reset_mock()
            self.assertTrue(self.actions.is_fast_command(phrase))
            self.actions.handle(phrase)
            url = self.actions.web.call_args.args[0]
            self.assertEqual(parse_qs(urlsplit(url).query)["q"],["котов"])

    def test_missing_or_expired_topic_asks_instead_of_guessing(self):
        self.assertEqual(self.actions.handle("в браузере мне его открой").action,"ask")
        with patch("capri.automation.command_dispatcher.time.monotonic",return_value=0):
            self.actions.remember_search("old topic")
        with patch("capri.automation.command_dispatcher.time.monotonic",return_value=601):
            self.assertEqual(self.actions.handle("открой это").action,"ask")
        self.actions.web.assert_not_called()

    def test_information_request_sets_topic_but_does_not_open_browser(self):
        self.actions.handle("найди информацию про космос")
        self.assertEqual(self.actions.last_search_query,"космос")
        self.actions.web.assert_not_called()

    def test_negation_or_quoted_command_cannot_open_browser(self):
        for phrase in ("не открой котов в браузере","как открыть котов в браузере",'он сказал "открой котов в браузере"'):
            self.assertIsNone(self.actions.browser_request(phrase))
            self.assertFalse(self.actions.is_fast_command(phrase))
