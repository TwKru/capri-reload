"""Плавная ходьба и повороты: команды, цикл, направление, остановка и игровой режим."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
import avatar  # noqa: E402
from actions import Actions  # noqa: E402


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.assets = Path(__file__).resolve().parents[1] / "assets"

    def setUp(self):
        self.view = avatar.Avatar(str(self.assets))
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.overlay.close)

    def test_both_motions_have_96_frames_and_bounded_caches(self):
        for name in ("walk", "spin"):
            frames = self.view.anims[name]
            self.assertEqual(len(frames), 96)
            self.assertEqual(frames.fps, 60)
            for i in range(96):
                self.assertFalse(frames[i].isNull())
            self.assertLessEqual(len(frames.cache), 8)
            self.assertLessEqual(len(frames.keys.cache), 8)
            self.assertNotEqual(frames[0], frames[24])
            self.assertEqual(frames[-1], frames[95])

    def test_walk_can_start_while_visible_without_hiding_first(self):
        self.view.state = "visible"
        with patch.object(self.view, "raise_"):
            self.view.start_roam()
        self.assertTrue(self.view.roaming)
        self.assertTrue(self.view.timer.isActive())
        self.assertEqual(self.view.timer.interval(), 16)
        self.view.state = "visible"
        self.view.roam_last = 100
        position = self.view.roam_x
        self.view._roam_step(100.05)
        self.assertAlmostEqual(abs(self.view.roam_x - position), 7)
        self.assertAlmostEqual(self.view.walk_time, .0325)

    def test_walk_faces_its_direction_and_loops(self):
        self.view.roaming = True
        self.view.walk_time = .4
        self.view.roam_dir = 1
        right = self.view._figure()
        self.view.roam_dir = -1
        left = self.view._figure()
        self.assertEqual(left, avatar.flip_horizontal(right))
        self.view.walk_time += 1.6
        self.assertEqual(self.view._figure(), left)

    def test_stop_cancels_walking_and_spin(self):
        with patch.object(self.view, "raise_"):
            self.view.start_roam()
        self.view.play_anim("spin")
        self.view.stop_motion()
        self.assertFalse(self.view.roaming)
        self.assertIsNone(self.view.anim)

    def test_smooth_motion_does_not_freeze_for_glitch_frames(self):
        self.view.state = "visible"
        self.view.play_anim("spin")
        self.view.lag = 20
        with patch.object(self.view, "render") as render:
            self.view.tick()
        render.assert_called_once()
        self.assertEqual(self.view.timer.interval(), 16)

    def test_game_mode_allows_requested_motion_at_lower_frame_rate(self):
        self.view.set_game_mode(True)
        self.view.play_anim("spin")
        self.view.start_roam()
        self.assertTrue(self.view.roaming)
        self.assertEqual(self.view.timer.interval(), 33)
        self.assertTrue(self.view.isVisible())

    def test_direct_motion_commands_do_not_need_ai(self):
        with patch("actions.AppIndex.build"):
            actions = Actions({}, ".", None)
        for command in ("походи", "походить", "ходи", "погуляй", "пройдись"):
            with self.subTest(command=command):
                self.assertEqual(actions.handle(command).action, "roam")
                self.assertTrue(actions.is_fast_command(command))
        for command in ("покрутись", "покружись", "повернись"):
            self.assertEqual(actions.handle(command).action, "anim:spin")


if __name__ == "__main__":
    unittest.main()
