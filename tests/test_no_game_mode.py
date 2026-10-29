import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from avatar import Avatar  # noqa: E402
from local_ai import LocalAI  # noqa: E402
import main  # noqa: E402


class NormalOperationTests(unittest.TestCase):
    def test_no_automatic_game_setting_or_cpu_restriction(self):
        self.assertNotIn("auto_game_mode", main.DEFAULTS)
        self.assertFalse(hasattr(main.Capri, "set_game_mode"))
        options = LocalAI({})._options(160)
        self.assertNotIn("num_gpu", options)
        self.assertNotIn("num_thread", options)

    def test_normal_startup_always_preloads_installed_model(self):
        ai = LocalAI({})
        with patch.object(ai, "installed", return_value=[ai.model]), patch("local_ai._post") as request:
            ai.start_server()
        self.assertEqual(request.call_args.args[0], "/api/generate")
        self.assertNotEqual(request.call_args.args[1].get("keep_alive"), 0)

    def test_avatar_appears_immediately_without_activating_window(self):
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        avatar = Avatar(os.path.join(main.BASE, "assets"))
        self.addCleanup(avatar.close)
        self.addCleanup(avatar.overlay.close)
        self.addCleanup(avatar.timer.stop)
        self.assertFalse(hasattr(avatar, "set_game_mode"))
        with patch.object(avatar, "raise_"):
            avatar.summon()
        self.assertEqual(avatar.state, "visible")
        self.assertTrue(avatar.isVisible())
        self.assertTrue(avatar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
