"""Action sprites and random poses work even after optional clips are deleted."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from capri.desktop.avatar import POSE_DURATION, POSE_INTERVAL, Avatar


class AvatarPoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.assets = Path(folder.name)
        poses = self.assets / "poses"
        poses.mkdir()
        for name, color in (("capri", "red"), ("capri_roam", "green"), ("capri_answer", "blue")):
            image = QImage(40, 40, QImage.Format.Format_ARGB32)
            image.fill(QColor(color))
            self.assertTrue(image.save(str(poses / (name + ".png"))))
        self.view = Avatar(str(self.assets))
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.overlay.close)
        self.addCleanup(self.view.timer.stop)
        self.view.state = "visible"

    def test_flight_sprite_wins_over_speech_and_old_animations(self):
        self.view.set_mode("speaking")
        self.view.start_roam()
        self.view.anim = "deleted_animation"
        self.assertEqual(self.view._figure(), self.view.roam_img)

    def test_answer_sprite_wins_over_perching_and_old_animations(self):
        self.view.perched = True
        self.view.anim = "deleted_animation"
        self.view.set_mode("speaking")
        self.assertEqual(self.view._figure(), self.view.answer_img)

    def test_random_pose_overrides_every_activity_then_restores_action(self):
        for activity in ("idle", "listening", "thinking", "speaking", "flight", "sleep", "animation", "perch"):
            with self.subTest(activity=activity), patch("capri.desktop.avatar.time.monotonic", return_value=100):
                view = self.view
                view.roaming = activity == "flight"
                view.sleeping = activity == "sleep"
                view.perched = activity == "perch"
                view.mode = activity if activity in ("listening", "thinking", "speaking") else "idle"
                view.anim = "test" if activity == "animation" else None
                view.anims["test"] = [view.answer_img]
                view.anim_start, view.anim_loop = 0, True
                view.pose_override = None
                normal = view._figure()
                view.next_pose = 100
                with patch("capri.desktop.avatar.random.random", return_value=0):
                    view._pose_step()
                self.assertNotEqual(view._figure(), normal)
                self.assertEqual(view.next_pose, 100 + POSE_INTERVAL)
                with patch("capri.desktop.avatar.time.monotonic", return_value=100 + POSE_DURATION):
                    view._pose_step()
                    self.assertEqual(view._figure(), normal)

    def test_failed_chance_waits_full_interval_and_never_retries_each_frame(self):
        self.view.next_pose = 100
        with patch("capri.desktop.avatar.random.random", return_value=.99) as chance:
            self.view._pose_step(100)
            self.view._pose_step(109.999)
            self.assertEqual(chance.call_count, 1)
            self.assertIsNone(self.view.pose_override)
            self.view._pose_step(110)
            self.assertEqual(chance.call_count, 2)

    def test_empty_assets_allow_flight_and_answer(self):
        for path in (self.assets / "poses").iterdir():
            path.unlink()
        view = Avatar(str(self.assets))
        self.addCleanup(view.close)
        self.addCleanup(view.overlay.close)
        self.addCleanup(view.timer.stop)
        view.set_mode("speaking")
        self.assertFalse(view._figure().isNull())
        view.start_roam()
        self.assertFalse(view._figure().isNull())
