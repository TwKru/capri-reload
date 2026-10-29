"""Команды плеера без переключения реальных треков и окон."""
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import media
from actions import Actions


class PlaybackCommandTests(unittest.TestCase):
    def setUp(self):
        with patch("actions.AppIndex.build"):
            self.app = Actions({}, ".", None)
        self.app.web = Mock()

    def test_like_commands_use_music_page_and_report_only_verified_success(self):
        for command in ("поставь лайк песне", "лайкни трек", "лайк", "добавь песню в понравившиеся"):
            with self.subTest(command=command), patch("actions.media.music_page_control", return_value=True) as like:
                self.assertEqual(self.app.handle(command).text, "Песне поставлен лайк.")
                like.assert_called_once_with("like", True)
        with patch("actions.media.music_page_control", return_value=False):
            self.assertIn("Не удалось", self.app.handle("лайкни песню").text)

    def test_next_previous_phrases(self):
        for command, action in (("включи следующую песню", "next"), ("следующая песня", "next"),
                                ("поставь предыдущую песню", "prev"), ("предыдущая песня", "prev"),
                                ("некст", "next"), ("некст трек", "next"), ("next", "next"),
                                ("next track", "next"), ("скип", "next"), ("skip song", "next"),
                                ("прев", "prev"), ("previous track", "prev")):
            with self.subTest(command=command), \
                    patch("actions.media.control", return_value=(True, "Song", "player")) as control, \
                    patch("actions.media.now_playing", return_value=None), patch("actions.time.sleep"), \
                    patch("actions.media.music_page_control") as fallback:
                self.app.handle(command)
                control.assert_called_once_with(action)
                fallback.assert_not_called()

    def test_next_uses_page_when_system_control_fails(self):
        with patch("actions.media.control", return_value=(False, None, None)), \
                patch("actions.media.music_page_control", return_value=True) as fallback, \
                patch("actions.media.now_playing", side_effect=RuntimeError), patch("actions.time.sleep"):
            self.app.handle("включи следующую песню")
            fallback.assert_called_once_with("next")

    def test_misheard_next_is_corrected_only_in_media_context(self):
        with patch("actions.media.now_playing", return_value=("Song", "player", True)):
            self.assertEqual(self.app.normalize_voice_command("текст"), "следующий трек")
            self.assertEqual(self.app.normalize_voice_command("текст трек"), "следующий трек")
            self.assertEqual(self.app.normalize_voice_command("напиши текст"), "напиши текст")
            self.assertEqual(self.app.normalize_voice_command("объясни этот текст"), "объясни этот текст")
        with patch("actions.media.now_playing", return_value=None), \
                patch("automation.find_window", return_value=None):
            self.assertEqual(self.app.normalize_voice_command("текст"), "текст")

    def test_misheard_next_works_with_music_page_without_system_session(self):
        with patch("actions.media.now_playing", side_effect=RuntimeError), \
                patch("automation.find_window", return_value=123):
            self.assertEqual(self.app.normalize_voice_command("текст"), "следующий трек")

    def test_repeat_and_shuffle_values(self):
        commands = (("зацикли песню", "repeat", "track"),
                    ("зацикли плейлист", "repeat", "list"),
                    ("включи повтор всех песен", "repeat", "list"),
                    ("выключи повтор", "repeat", "off"),
                    ("сними зацикливание", "repeat", "off"),
                    ("перемешай песни", "shuffle", True),
                    ("включи перемешивание", "shuffle", True),
                    ("выключи перемешивание", "shuffle", False))
        for command, action, value in commands:
            with self.subTest(command=command), \
                    patch("actions.media.playback_mode", return_value=True) as mode, \
                    patch("actions.media.music_page_control") as fallback:
                reply = self.app.handle(command)
                self.assertIsNotNone(reply)
                self.assertNotIn("Не удалось", reply.text)
                mode.assert_called_once_with(action, value)
                fallback.assert_not_called()

    def test_unsupported_mode_is_not_reported_as_success(self):
        with patch("actions.media.playback_mode", return_value=False), \
                patch("actions.media.music_page_control", return_value=False):
            self.assertIn("Не удалось", self.app.handle("зацикли песню").text)


class SystemModeTests(unittest.TestCase):
    def test_winrt_modes_and_shuffle(self):
        controls = types.SimpleNamespace(is_repeat_enabled=True, is_shuffle_enabled=True)
        session = types.SimpleNamespace(
            get_playback_info=lambda: types.SimpleNamespace(controls=controls),
            try_change_auto_repeat_mode_async=AsyncMock(return_value=True),
            try_change_shuffle_active_async=AsyncMock(return_value=True))
        with patch.object(media, "_pick", AsyncMock(return_value=session)):
            for value, expected in (("off", 0), ("track", 1), ("list", 2)):
                self.assertTrue(media.playback_mode("repeat", value))
                self.assertEqual(session.try_change_auto_repeat_mode_async.call_args.args[0], expected)
            self.assertTrue(media.playback_mode("shuffle", False))
            session.try_change_shuffle_active_async.assert_awaited_once_with(False)
            controls.is_shuffle_enabled = False
            session.try_change_shuffle_active_async.reset_mock()
            self.assertFalse(media.playback_mode("shuffle", True))
            session.try_change_shuffle_active_async.assert_not_called()

    def test_no_session_returns_false(self):
        with patch.object(media, "_pick", AsyncMock(return_value=None)):
            self.assertFalse(media.playback_mode("repeat", "track"))

    def test_metadata_failure_does_not_hide_successful_skip(self):
        session = Mock()
        session.try_skip_next_async = AsyncMock(return_value=True)
        session.source_app_user_model_id = "player"
        with patch.object(media, "_pick", AsyncMock(return_value=session)), \
                patch.object(media, "_describe", AsyncMock(side_effect=RuntimeError)):
            self.assertEqual(media.control("next"), (True, "", "player"))
            session.try_skip_next_async.assert_awaited_once()


class MusicPageTests(unittest.TestCase):
    def execute(self, action, value, button, invoke):
        with patch("automation.find_window", return_value=123), \
                patch.object(media, "browser_url", return_value="https://music.youtube.com/watch?v=example"), \
                patch.object(media, "_music_buttons", return_value=[button]), \
                patch.object(media, "_invoke_music_button", side_effect=invoke) as click, \
                patch.object(media.time, "sleep"):
            result = media.music_page_control(action, value)
            return result, click.call_count

    def test_like_is_verified_and_repeat_request_does_not_unlike(self):
        for label in ("Нравится", "Like this song"):
            button = types.SimpleNamespace(CurrentName=label, CurrentIsEnabled=True,
                                           CurrentAriaProperties="pressed=false")
            def invoke(b):
                b.CurrentAriaProperties = "pressed=true"
            self.assertEqual(self.execute("like", True, button, invoke), (True, 1))
            self.assertEqual(self.execute("like", True, button, invoke), (True, 0))

    def test_like_reads_chromium_toggle_pattern_without_aria_properties(self):
        button = Mock(CurrentName="Нравится", CurrentIsEnabled=True, CurrentAriaProperties="")
        toggle = button.GetCurrentPattern.return_value.QueryInterface.return_value
        toggle.CurrentToggleState = 0
        def invoke(b):
            toggle.CurrentToggleState = 1
        self.assertEqual(self.execute("like", True, button, invoke), (True, 1))
        self.assertEqual(self.execute("like", True, button, invoke), (True, 0))
        toggle.CurrentToggleState = 2
        self.assertEqual(self.execute("like", True, button, invoke), (False, 0))

    def test_like_without_state_never_toggles_blindly(self):
        button = types.SimpleNamespace(CurrentName="Нравится", CurrentIsEnabled=True, CurrentAriaProperties="")
        self.assertEqual(self.execute("like", True, button, lambda b: None), (False, 0))
        button.CurrentAriaProperties = "pressed=false"
        self.assertEqual(self.execute("like", True, button, lambda b: None), (False, 1))

    def test_dislike_cannot_be_used_as_like(self):
        for label in ("Не нравится", "Dislike", "Remove dislike", "Больше не нравится"):
            button = types.SimpleNamespace(CurrentName=label, CurrentIsEnabled=True, CurrentAriaProperties="pressed=false")
            self.assertEqual(self.execute("like", True, button, lambda b: None), (False, 0))

    def test_like_rejects_other_domains_without_clicking(self):
        with patch("automation.find_window", return_value=123), patch.object(media, "_music_buttons") as buttons:
            for url in (None, "https://youtube.com/watch?v=1", "https://music.youtube.com.example.org/"):
                with patch.object(media, "browser_url", return_value=url):
                    self.assertFalse(media.music_page_control("like", True))
            buttons.assert_not_called()

    def test_repeat_cycles_until_requested_state_then_stops(self):
        button = types.SimpleNamespace(CurrentName="Повтор отключен", CurrentIsEnabled=True,
                                       CurrentAriaProperties="")
        labels = iter(("Повторять все", "Повторять один трек"))
        def invoke(b):
            b.CurrentName = next(labels)
        self.assertEqual(self.execute("repeat", "track", button, invoke), (True, 2))
        self.assertEqual(self.execute("repeat", "track", button, invoke), (True, 0))

    def test_known_shuffle_mode_is_idempotent(self):
        button = types.SimpleNamespace(CurrentName="Shuffle", CurrentIsEnabled=True,
                                       CurrentAriaProperties="pressed=true")
        self.assertEqual(self.execute("shuffle", True, button, lambda b: None), (True, 0))

    def test_youtube_shuffle_action_runs_once(self):
        button = types.SimpleNamespace(CurrentName="Перемешать", CurrentIsEnabled=True,
                                       CurrentAriaProperties="")
        self.assertEqual(self.execute("shuffle", True, button, lambda b: None), (True, 1))
        self.assertEqual(self.execute("shuffle", False, button, lambda b: None), (False, 0))

    def test_player_bar_next_previous_labels(self):
        for label, action in (("Далее", "next"), ("Назад", "prev")):
            button = types.SimpleNamespace(CurrentName=label, CurrentIsEnabled=True)
            self.assertEqual(self.execute(action, None, button, lambda b: None), (True, 1))

    def test_unknown_repeat_state_is_not_clicked(self):
        button = types.SimpleNamespace(CurrentName="Повтор", CurrentIsEnabled=True)
        self.assertEqual(self.execute("repeat", "track", button, lambda b: None), (False, 0))

    def test_play_button_resumes_and_does_not_pause_playing_track(self):
        button = types.SimpleNamespace(CurrentName="Воспроизвести", CurrentIsEnabled=True)
        def invoke(b):
            b.CurrentName = "Приостановить"
        self.assertEqual(self.execute("play", None, button, invoke), (True, 1))
        self.assertEqual(self.execute("play", None, button, invoke), (True, 0))

    def test_other_websites_are_not_controlled(self):
        with patch("automation.find_window", return_value=123), \
                patch.object(media, "browser_url", return_value="https://example.com/"), \
                patch.object(media, "_music_buttons") as buttons:
            self.assertFalse(media.music_page_control("next"))
            buttons.assert_not_called()


if __name__ == "__main__":
    unittest.main()
