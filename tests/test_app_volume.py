"""Управление громкостью отдельных приложений без изменения настоящего звука."""
import types
import unittest
from unittest.mock import Mock, patch

from actions import Actions


class AppVolumeTests(unittest.TestCase):
    def setUp(self):
        with patch("actions.AppIndex.build"):
            self.app = Actions({"app_aliases": {"говорилка": "chatclient"},
                                "apps": {"игра": r"C:\Games\GamePlayer.exe"}}, ".", None)
        self.volumes = {}
        self.sessions = []
        for name, label in (("Discord.exe", "Discord"), ("Telegram.exe", "Telegram"),
                            ("steamwebhelper.exe", "Steam"), ("chatclient.exe", "Chat client"),
                            ("GamePlayer.exe", "My Game"), ("Dota2.exe", "Dota 2"),
                            ("music.exe", "Яндекс Музыка"), ("chrome.exe", "Google Chrome")):
            volume = Mock()
            volume.GetMasterVolume.return_value = 0.7
            self.volumes[name.lower()] = volume
            process = types.SimpleNamespace(name=lambda name=name: name, exe=lambda: "")
            self.sessions.append(types.SimpleNamespace(Process=process, DisplayName=label, SimpleAudioVolume=volume))
        self.sessions_patch = patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=self.sessions)
        self.sessions_patch.start()
        self.addCleanup(self.sessions_patch.stop)
        self.endpoint_patch = patch("actions._endpoint")
        self.endpoint = self.endpoint_patch.start()
        self.addCleanup(self.endpoint_patch.stop)

    def tearDown(self):
        self.endpoint.assert_not_called()

    def test_absolute_volume_and_cases(self):
        for command in ("громкость дискорда 30", "сделай громкость в дискорде на 30 процентов",
                        "громкость 30 в дискорде", "установи громкость программы дискорд 30"):
            with self.subTest(command=command):
                volume = self.volumes["discord.exe"]
                volume.reset_mock()
                self.app.handle(command)
                volume.SetMasterVolume.assert_called_once_with(0.3, None)
                self.volumes["telegram.exe"].SetMasterVolume.assert_not_called()

    def test_relative_volume_and_zero_delta(self):
        for command, expected in (("сделай телеграм тише", 0.6),
                                  ("сделай телеграм потише", 0.6),
                                  ("уменьши звук телеграма на 20", 0.5),
                                  ("сделай телеграм громче на 20", 0.9),
                                  ("телеграм тише на ноль", 0.7),
                                  ("уменьши громкость телеграма до 30", 0.3)):
            with self.subTest(command=command):
                volume = self.volumes["telegram.exe"]
                volume.reset_mock()
                self.app.handle(command)
                volume.SetMasterVolume.assert_called_once_with(expected, None)

    def test_mute_and_unmute_steam_helper(self):
        volume = self.volumes["steamwebhelper.exe"]
        self.app.handle("выключи звук стима")
        volume.SetMute.assert_called_once_with(True, None)
        volume.reset_mock()
        self.app.handle("включи звук в стиме")
        volume.SetMute.assert_called_once_with(False, None)
        volume.SetMasterVolume.assert_not_called()

    def test_unknown_target_never_changes_system_volume(self):
        reply = self.app.handle("громкость неизвестной программы 20")
        self.assertIn("Не нашла звуковую сессию", reply.text)
        for volume in self.volumes.values():
            volume.SetMasterVolume.assert_not_called()

    def test_custom_alias_and_executable_path(self):
        self.app.handle("громкость говорилки 10")
        self.volumes["chatclient.exe"].SetMasterVolume.assert_called_once_with(0.1, None)
        self.app.handle("громкость игры 20")
        self.volumes["gameplayer.exe"].SetMasterVolume.assert_called_once_with(0.2, None)

    def test_digits_in_app_name_do_not_become_volume(self):
        self.app.handle("громкость dota2 40")
        volume = self.volumes["dota2.exe"]
        volume.SetMasterVolume.assert_called_once_with(0.4, None)
        volume.reset_mock()
        self.app.handle("какая громкость dota2")
        volume.GetMasterVolume.assert_called()
        volume.SetMasterVolume.assert_not_called()

    def test_product_name_is_not_confused_with_browser(self):
        self.app.handle("громкость яндекс музыки 30")
        self.volumes["music.exe"].SetMasterVolume.assert_called_once_with(0.3, None)
        self.volumes["chrome.exe"].SetMasterVolume.assert_not_called()

    def test_all_sessions_of_same_app_are_changed(self):
        other = Mock()
        other.GetMasterVolume.return_value = 0.5
        self.sessions.append(types.SimpleNamespace(Process=types.SimpleNamespace(name=lambda: "Discord.exe"),
                                                    SimpleAudioVolume=other))
        self.app.handle("громкость дискорда 20")
        other.SetMasterVolume.assert_called_once_with(0.2, None)
        self.volumes["discord.exe"].SetMasterVolume.assert_called_once_with(0.2, None)

    def test_volume_is_clamped(self):
        self.app.handle("сделай телеграм громче на 90")
        self.volumes["telegram.exe"].SetMasterVolume.assert_called_once_with(1.0, None)


if __name__ == "__main__":
    unittest.main()
