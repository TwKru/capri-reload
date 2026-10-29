import copy
import unittest
from unittest.mock import Mock, patch

from local_ai import LocalAI
import cancellation
from model_policy import ConversationModels, game_window, game_running
import main


class GameDetectionTests(unittest.TestCase):
    def test_background_rust_keeps_light_model_until_game_exits(self):
        models = ConversationModels({})
        installed = Mock(return_value=["qwen3:8b", "qwen3:1.7b"])
        rust = Mock(info={"name": "RustClient.exe", "exe": ""})
        with patch("model_policy.psutil.process_iter", return_value=[rust]) as processes, \
                patch("model_policy.foreground_game", return_value=False):
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:1.7b")
            processes.return_value = []
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:8b")

    def test_background_game_paths_and_custom_names_are_detected(self):
        for name, exe, extra in (
                ("another.exe", r"D:\Steam\steamapps\common\Game\another.exe", ()),
                ("custom.exe", "", {"custom.exe"})):
            with patch("model_policy.psutil.process_iter", return_value=[Mock(info={"name": name, "exe": exe})]), \
                    patch("model_policy.foreground_game", return_value=False):
                self.assertTrue(game_running(extra))

    def test_background_launchers_and_crash_helpers_do_not_keep_game_model(self):
        processes = [Mock(info={"name": name, "exe": "D:/Steam/steamapps/common/Game/" + name})
                     for name in ("steam.exe", "UnityCrashHandler64.exe", "crashpad_handler.exe")]
        with patch("model_policy.psutil.process_iter", return_value=processes), \
                patch("model_policy.foreground_game", return_value=False):
            self.assertFalse(game_running())

    def test_known_windowed_game_is_detected(self):
        self.assertTrue(game_window("RustClient.exe", r"D:\Steam\steamapps\common\Rust\RustClient.exe",
                                    (50, 50, 1000, 800), (0, 0, 1920, 1080), 0x00C00000))

    def test_fullscreen_browser_and_maximized_tools_are_not_games(self):
        for name in ("chrome.exe", "msedge.exe", "vlc.exe", "steam.exe", "pythonw.exe"):
            self.assertFalse(game_window(name, "", (0, 0, 1920, 1080), (0, 0, 1920, 1080), 0))
        self.assertFalse(game_window("editor.exe", "", (-8, -8, 1928, 1088), (0, 0, 1920, 1080), 0x00C00000))

    def test_other_fullscreen_game_and_explicit_game_name_are_supported(self):
        self.assertTrue(game_window("game.exe", "", (1920, 0, 4480, 1440), (1920, 0, 4480, 1440), 0))
        self.assertTrue(game_window("custom.exe", "", (20, 20, 900, 800), (0, 0, 1920, 1080), 0x00C00000, {"custom.exe"}))


class ModelChoiceTests(unittest.TestCase):
    def test_temporary_ollama_failure_does_not_cache_missing_model_or_switch_to_heavy(self):
        models = ConversationModels({})
        installed = Mock(side_effect=[None, ["qwen3:8b", "qwen3:1.7b"]])
        with patch("model_policy.game_running", return_value=True):
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:1.7b")
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:1.7b")
        self.assertEqual(installed.call_count, 2)

    def test_game_uses_installed_light_model_and_desktop_uses_normal(self):
        models = ConversationModels({})
        installed = Mock(return_value=["qwen3:8b", "qwen3:1.7b", "qwen3:0.6b"])
        with patch("model_policy.game_running", return_value=True):
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:1.7b")
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:1.7b")
        installed.assert_called_once()
        with patch("model_policy.game_running", return_value=False):
            self.assertEqual(models.choose("qwen3:8b", installed), "qwen3:8b")

    def test_missing_game_model_uses_main_model_not_dispatcher(self):
        with patch("model_policy.game_running", return_value=True):
            self.assertEqual(ConversationModels({}).choose("qwen3:8b", lambda: ["qwen3:8b", "qwen3:0.6b"]), "qwen3:8b")

    def test_model_released_only_when_actual_model_selection_changes(self):
        models, release = ConversationModels({}), Mock()
        models.prepare("qwen3:1.7b", "qwen3:8b", release)
        models.prepare("qwen3:1.7b", "qwen3:8b", release)
        release.assert_called_once_with("qwen3:8b")
        models.prepare("qwen3:8b", "qwen3:8b", release)
        self.assertEqual(release.call_args.args, ("qwen3:1.7b",))
        self.assertEqual(release.call_count, 2)

    def test_disabled_policy_never_reads_foreground_or_changes_model(self):
        with patch("model_policy.game_running") as foreground:
            models = ConversationModels({"use_light_model_in_games": False})
            self.assertEqual(models.choose("qwen3:8b", Mock()), "qwen3:8b")
            foreground.assert_not_called()

    def test_request_model_switch_keeps_primary_setting_and_dialogue_history(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, intent_router=False)
        with patch.object(main, "Actions"), patch.object(main, "Speaker"), patch.object(main, "AI"), patch.object(main, "make_glitch_sound"):
            capri = main.Capri(cfg)
        observed, released = [], []
        class TestAI(LocalAI):
            @staticmethod
            def installed():
                return ["qwen3:8b", "qwen3:1.7b"]
            @staticmethod
            def release_model(model):
                released.append(model)
            def ask(self, question):
                observed.append(self.model)
                self.history.append({"role": "assistant", "content": "Ответ."})
                return "Ответ."
        ai = TestAI({})
        with patch("model_policy.game_running", return_value=True):
            self.assertEqual(capri._ask_ai(ai, "Вопрос", lambda: False), "Ответ.")
        with patch("model_policy.game_running", return_value=False):
            self.assertEqual(capri._ask_ai(ai, "Другой вопрос", lambda: False), "Ответ.")
        self.assertEqual(observed, ["qwen3:1.7b", "qwen3:8b"])
        self.assertEqual(released, ["qwen3:8b", "qwen3:1.7b"])
        self.assertEqual(ai.model, "qwen3:8b")
        self.assertEqual(len(ai.history), 2)
        self.assertNotIn("auto_game_mode", main.DEFAULTS)

    def test_spontaneous_and_report_speech_use_game_model(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, intent_router=False)
        with patch.object(main, "Actions"), patch.object(main, "Speaker"), patch.object(main, "AI"), patch.object(main, "make_glitch_sound"):
            capri = main.Capri(cfg)
        capri.local = LocalAI({})
        with patch("model_policy.game_running", return_value=True), \
                patch.object(LocalAI, "installed", return_value=["qwen3:8b", "qwen3:1.7b"]), \
                patch.object(LocalAI, "release_model"), \
                patch.object(LocalAI, "_chat", autospec=True, side_effect=lambda ai, *args, **kwargs: ai.model):
            self.assertEqual(capri._local_reply("summarize_report", "report"), "qwen3:1.7b")
            capri._local_reply("chatter", "")
        self.assertEqual(capri.local.model, "qwen3:8b")
        with patch.object(capri, "_ask_ai", return_value=main.AI_CANCELLED):
            with self.assertRaises(cancellation.RequestCancelled):
                capri._local_reply("chatter", "")
