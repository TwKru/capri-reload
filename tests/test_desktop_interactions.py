"""Imported clips stay bounded; mouse gestures and sleep do not block voice commands."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import avatar  # noqa: E402
from actions import Actions  # noqa: E402


class DesktopInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.assets = Path(__file__).resolve().parents[1] / "assets"

    def setUp(self):
        avatar.SpriteStripFrames.strips.clear()
        avatar.SpriteStripFrames.cache.clear()
        self.view = avatar.Avatar(str(self.assets))
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.overlay.close)
        self.addCleanup(self.view.timer.stop)
        self.view.state = "visible"

    def test_clips_are_lazy_and_share_bounded_memory(self):
        self.assertEqual(len(avatar.SpriteStripFrames.strips), 0)
        self.assertEqual(len(avatar.SpriteStripFrames.cache), 0)
        for name in ("idle", "blink", "grin", "drag", "sleep", "wake", "dance"):
            frames = self.view.anims["desktop_" + name]
            for index in range(len(frames)):
                self.assertFalse(frames[index].isNull())
                self.assertLessEqual(len(frames.strips), 1)
                self.assertLessEqual(len(frames.cache), 8)
        self.assertNotEqual(self.view.anims["desktop_sleep"][0], self.view.anims["desktop_wake"][4])

    def test_pat_requires_repeated_strokes_and_has_cooldown(self):
        events = []
        self.view.petted.connect(lambda: events.append(True))
        for index, x in enumerate((150, 180, 140, 180, 140)):
            self.view.stroke_head(QPointF(x, 60), 10 + index * .15)
        self.assertEqual(events, [True])
        self.assertEqual(self.view.anim, "desktop_grin")
        for index, x in enumerate((180, 140, 180, 140)):
            self.view.stroke_head(QPointF(x, 60), 11 + index * .1)
        self.assertEqual(events, [True])

    def test_moving_over_subtitles_cannot_pet(self):
        for index, x in enumerate((150, 180, 140, 180, 140)):
            self.assertFalse(self.view.stroke_head(QPointF(x, 430), 10 + index * .15))
        self.assertIsNone(self.view.anim)

    def test_sleep_stays_visible_and_wakes_on_summon(self):
        self.view.play_anim("sleep")
        self.view.set_mode("idle")
        self.assertTrue(self.view.sleeping)
        self.assertEqual(self.view.hide_at, 0)
        self.view.tick()
        self.assertEqual(self.view.timer.interval(), 166)
        with patch.object(self.view, "raise_"):
            self.view.summon()
        self.view.set_mode("listening", 8)
        self.assertFalse(self.view.sleeping)
        self.assertEqual(self.view.anim, "desktop_wake")
        self.assertEqual(self.view.mode, "listening")
        self.assertTrue(self.view.isVisible())

    def test_game_mode_keeps_idle_static_and_allows_explicit_dance(self):
        self.view.set_game_mode(True)
        first = self.view._figure()
        with patch("avatar.time.time", return_value=avatar.time.time() + 3):
            self.assertEqual(self.view._figure(), first)
        self.view.play_anim("dance")
        self.view.tick()
        self.assertEqual(self.view.anim, "desktop_dance")
        self.assertEqual(self.view.timer.interval(), 33)
        self.view.stop_motion()
        self.assertIsNone(self.view.anim)

    def test_drag_threshold_does_not_turn_a_click_into_a_drag(self):
        event = lambda x, y: SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
            globalPosition=lambda: QPointF(x, y), position=lambda: QPointF(x, y))
        self.view.mousePressEvent(event(100, 100))
        self.view.mouseMoveEvent(event(101, 101))
        self.assertFalse(self.view._moved)
        self.view.mouseMoveEvent(event(150, 130))
        self.assertTrue(self.view._moved)
        self.assertIsNotNone(self.view._press)
        self.view._figure()
        self.view.mouseReleaseEvent(event(150, 130))
        self.assertIsNone(self.view._press)
        self.assertEqual(self.view.anim, "desktop_grin")
        rect = QApplication.primaryScreen().availableGeometry()
        self.assertTrue(rect.contains(self.view.pos()))

    def test_new_commands_use_local_handlers(self):
        with patch("actions.AppIndex.build"):
            actions = Actions({}, ".", None)
        for command, animation in (("поспи", "sleep"), ("ложись спать", "sleep"),
                                   ("проснись", "wake"), ("танцуй", "dance")):
            self.assertEqual(actions.handle(command).action, "anim:" + animation)
            self.assertTrue(actions.is_fast_command(command))
