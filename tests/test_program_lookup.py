"""Интернет даёт только имена; действия выполняются только над найденными локальными программами."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from actions import Actions, Reply
from program_lookup import ProgramLookup, abbreviation_spellings, name_key, steam_games


class LookupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "names.json"

    def test_disambiguation_candidates_are_cached_between_runs(self):
        data = {"query": {"pages": [{"title": "CS2", "pageprops": {"disambiguation": ""},
            "links": [{"title": "Counter-Strike 2"}, {"title": "Cities: Skylines II"}]}]}}
        resolver = ProgramLookup(cache_path=self.path)
        with patch.object(resolver, "_request", return_value=data) as request:
            names = resolver.resolve("cs2")
            self.assertIn("Counter-Strike 2", names)
            calls = request.call_count
            self.assertEqual(resolver.resolve("CS2"), names)
            self.assertEqual(request.call_count, calls)
        other = ProgramLookup(cache_path=self.path)
        with patch.object(other, "_request") as request:
            self.assertEqual(other.resolve("cs2"), names)
            request.assert_not_called()
        self.assertIn("cs2", json.loads(self.path.read_text(encoding="utf-8")))

    def test_regular_page_links_are_not_treated_as_app_aliases(self):
        data = {"query": {"pages": [{"title": "Discord (software)",
                  "links": [{"title": "Microsoft Windows"}, {"title": "Steam"}]}]}}
        resolver = ProgramLookup(cache_path=self.path)
        with patch.object(resolver, "_request", return_value=data):
            self.assertEqual(resolver.resolve("ds"), ["Discord (software)"])

    def test_unavailable_internet_does_not_retry_for_each_command(self):
        resolver = ProgramLookup(cache_path=self.path)
        with patch.object(resolver, "_request", side_effect=TimeoutError) as request:
            self.assertEqual(resolver.resolve("unknown"), [])
            count = request.call_count
            self.assertEqual(resolver.resolve("unknown"), [])
            self.assertEqual(request.call_count, count)

    def test_names_match_punctuation_and_roman_game_versions(self):
        self.assertEqual(name_key("Counter-Strike 2"), name_key("counter strike 2"))
        self.assertEqual(name_key("Cities: Skylines II"), name_key("Cities Skylines 2"))

    def test_spoken_cyrillic_initials_are_also_searched_in_latin(self):
        self.assertIn("CS2", abbreviation_spellings("кс2"))
        self.assertIn("KS2", abbreviation_spellings("кс 2"))
        self.assertEqual(abbreviation_spellings("cs2"), ["cs2", "CS2", "Cs2"])

    def test_steam_games_are_indexed_without_a_start_menu_shortcut(self):
        root = self.path.parent / "Steam"
        apps = root / "steamapps"
        (apps / "common" / "Counter Strike Global Offensive").mkdir(parents=True)
        (apps / "appmanifest_730.acf").write_text(
            '"AppState" { "appid" "730" "name" "Counter-Strike 2" '
            '"installdir" "Counter Strike Global Offensive" }', encoding="utf-8")
        self.assertEqual(steam_games([root]), [("Counter-Strike 2", "steam://rungameid/730")])


class WebAppCommandTests(unittest.TestCase):
    def setUp(self):
        with patch("actions.AppIndex.build"):
            self.app = Actions({"web_app_lookup": True}, ".", None)
        self.lookup = Mock()
        self.lookup.resolve.return_value = ["Counter-Strike 2"]
        self.app.program_lookup = self.lookup
        self.volume = Mock()
        self.volume.GetMasterVolume.return_value = 0.7
        self.sessions = [types.SimpleNamespace(
            Process=types.SimpleNamespace(name=lambda: "game64.exe", exe=lambda: "game64.exe"),
            DisplayName="Counter-Strike 2", SimpleAudioVolume=self.volume)]
        for replacement in (patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=self.sessions),
                            patch("actions.file_description", return_value="")):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.endpoint_patch = patch("actions._endpoint")
        self.endpoint = self.endpoint_patch.start()
        self.addCleanup(self.endpoint_patch.stop)

    def tearDown(self):
        self.endpoint.assert_not_called()

    def test_online_full_name_matches_local_audio_session(self):
        reply = self.app.handle("замуть cs2")
        self.lookup.resolve.assert_called_once_with("cs2")
        self.volume.SetMute.assert_called_once_with(True, None)
        self.assertIn("Counter-Strike 2", reply.text)

    def test_spoken_numeric_abbreviation_is_not_a_volume_value(self):
        for command in ("замути кс два", "выключи звук cs 2", "мутни кс2"):
            with self.subTest(command=command):
                self.volume.reset_mock()
                self.app.handle(command)
                self.volume.SetMute.assert_called_once_with(True, None)
                self.volume.SetMasterVolume.assert_not_called()
        self.app.handle("размути кс два")
        self.volume.SetMute.assert_called_with(False, None)

    def test_volume_after_app_number_is_preserved(self):
        self.app.handle("громкость cs 2 30")
        self.volume.SetMasterVolume.assert_called_once_with(0.3, None)
        self.volume.reset_mock()
        for command in ("какая громкость кс два", "какая громкость в программе cs 2"):
            self.app.handle(command)
            self.volume.SetMasterVolume.assert_not_called()

    def test_ambiguous_names_do_not_change_any_audio(self):
        self.lookup.resolve.return_value = ["Counter-Strike 2", "Cities: Skylines II"]
        other = Mock()
        self.sessions.append(types.SimpleNamespace(
            Process=types.SimpleNamespace(name=lambda: "cities2.exe", exe=lambda: "cities2.exe"),
            DisplayName="Cities: Skylines II", SimpleAudioVolume=other))
        reply = self.app.handle("замуть cs2")
        self.assertIn("Назови", reply.text)
        self.volume.SetMute.assert_not_called()
        other.SetMute.assert_not_called()

    def test_unmatched_online_name_never_changes_windows_volume(self):
        self.lookup.resolve.return_value = ["Unrelated program"]
        reply = self.app.handle("громкость cs2 30")
        self.assertIn("Не нашла", reply.text)
        self.volume.SetMasterVolume.assert_not_called()

    def test_missing_generic_program_does_not_become_global_volume(self):
        self.lookup.resolve.return_value = []
        self.app.handle("громкость программы тридцать")
        self.endpoint.assert_not_called()

    def test_open_matches_online_name_only_to_installed_entry(self):
        self.app.index.ready.set()
        self.app.index.items = {"counter-strike 2": ("file", "registered-shortcut.lnk")}
        with patch("actions.find_folder", return_value=None), \
                patch.object(self.app.index, "launch_best", return_value="counter-strike 2") as launch:
            self.app.handle("открой cs2")
        launch.assert_called_once_with("cs2", [(1.0, "counter-strike 2", ("file", "registered-shortcut.lnk"))])

    def test_close_uses_online_name_and_keeps_existing_process_protection(self):
        process = Mock()
        process.pid = 98765
        process.info = {"name": "game64.exe", "username": "test", "exe": "game64.exe"}
        self.app.index.ready.set()
        with patch("actions.psutil.Process") as current, patch("actions.psutil.process_iter", return_value=[process]), \
                patch("actions.file_description", return_value="Counter-Strike 2"), \
                patch.object(self.app, "_kill", return_value=Reply("Закрыла.")) as kill:
            current.return_value.username.return_value = "test"
            self.app.handle("закрой cs2")
        kill.assert_called_once_with("game64", [process], False)
        process.info["name"] = "explorer.exe"
        with patch("actions.psutil.Process") as current, patch("actions.psutil.process_iter", return_value=[process]), \
                patch("actions.file_description", return_value="Counter-Strike 2"), patch.object(self.app, "_kill") as kill:
            current.return_value.username.return_value = "test"
            self.app.handle("закрой cs2")
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
