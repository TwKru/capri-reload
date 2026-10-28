"""Включение музыки без реального управления плеером или браузером."""
import unittest
from unittest.mock import Mock, patch

from actions import Actions


class MusicTests(unittest.TestCase):
    def setUp(self):
        with patch("actions.AppIndex.build"):
            self.app = Actions({}, ".", None)
        self.app.web = Mock()
        self.page_control = patch("actions.media.music_page_control", return_value=False)
        self.page = self.page_control.start()
        self.addCleanup(self.page_control.stop)

    def test_resume_variants_are_dispatched_to_player(self):
        for command in ("продолжи", "продолжим", "продолжай", "продолжить",
                        "продолжи песню", "просто песню продолжи"):
            with self.subTest(command=command), \
                    patch("actions.media.control", return_value=(True, "Песня", "zen.exe")) as control, \
                    patch("actions.browser_playing") as sound, patch.object(self.app, "_youtube_keys") as keys:
                self.app.media_paused = "youtube"
                self.app.handle(command)
                control.assert_called_once_with("play", source=None)
                sound.assert_not_called()
                keys.assert_not_called()
        self.app.web.assert_not_called()

    def test_resume_uses_music_page_if_system_play_fails(self):
        self.page.return_value = True
        with patch("actions.media.control", return_value=(False, None, None)):
            reply = self.app.handle("продолжим")
        self.page.assert_called_once_with("play")
        self.assertNotIn("Не удалось", reply.text)
        self.app.web.assert_not_called()

    def test_play_resumes_without_opening_browser(self):
        for command in ("включи музыку", "запусти музыку", "поставь музыку"):
            with self.subTest(command=command):
                with patch("actions.media.control", return_value=(True, "Песня", "player.exe")) as control:
                    reply = self.app.handle(command)
                    control.assert_called_once_with("play", source=None)
                    self.assertNotIn("YouTube Music", reply.text)
        self.app.web.assert_not_called()

    def test_no_player_opens_youtube_music(self):
        with patch("actions.media.control", return_value=(False, None, None)):
            reply = self.app.handle("включи музыку")
        self.app.web.assert_called_once_with("https://music.youtube.com/")
        self.assertIn("YouTube Music", reply.text)

    def test_player_failure_opens_youtube_music(self):
        with patch("actions.media.control", side_effect=RuntimeError("Media API unavailable")):
            self.app.handle("включи музыку")
        self.app.web.assert_called_once_with("https://music.youtube.com/")

    def test_remembered_player_is_used(self):
        self.app.media_paused = "spotify.exe"
        with patch("actions.media.control", return_value=(True, "Песня", "spotify.exe")) as control:
            self.app.handle("включи музыку")
        control.assert_called_once_with("play", source="spotify.exe")
        self.assertIsNone(self.app.media_paused)
        self.app.web.assert_not_called()

    def test_youtube_marker_uses_current_system_session(self):
        self.app.media_paused = "youtube"
        with patch("actions.media.control", return_value=(True, "Песня", "zen.exe")) as control:
            self.app.handle("включи музыку")
        control.assert_called_once_with("play", source=None)
        self.app.web.assert_not_called()

    def test_named_music_search_keeps_existing_handler(self):
        self.app.routes = [(pattern, Mock(return_value=None) if fn == self.app.music else fn)
                           for pattern, fn in self.app.routes]
        with patch("actions.youtube_first", return_value=None), \
                patch("actions.ensure_playing"), patch("actions.media.control") as control:
            self.app.handle("включи музыку для работы")
        control.assert_not_called()


if __name__ == "__main__":
    unittest.main()
