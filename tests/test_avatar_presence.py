import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from capri.desktop.avatar import FIG_H, Avatar, W
from capri.desktop.window_companion import DesktopLife, Surface


class AvatarPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.assets = Path(__file__).resolve().parents[1]/"assets"

    def setUp(self):
        self.avatar = Avatar(str(self.assets))
        self.avatar.state = "visible"
        self.avatar.next_spin = float("inf")
        self.avatar.show()
        self.life = DesktopLife(self.avatar)
        self.addCleanup(self.avatar.close)
        self.addCleanup(self.avatar.overlay.close)
        self.addCleanup(self.avatar.timer.stop)
        self.addCleanup(self.life.timer.stop)

    def test_panel_only_in_active_modes_or_five_seconds_after_speech(self):
        view = self.avatar
        with patch("capri.desktop.avatar.time.monotonic",return_value=100):
            self.assertFalse(view.dialogue_visible())
            view.set_mode("listening")
            self.assertTrue(view.dialogue_visible())
            view.set_mode("thinking")
            self.assertTrue(view.dialogue_visible())
            view.set_subtitle("An answer")
            view.set_mode("speaking")
            self.assertTrue(view.dialogue_visible())
            view.set_mode("idle")
        self.assertTrue(view.dialogue_visible(104.999))
        self.assertFalse(view.dialogue_visible(105))
        self.assertFalse(view.dialogue_visible(120))

    def test_listening_after_reply_stays_visible_and_does_not_restart_expiry(self):
        view = self.avatar
        with patch("capri.desktop.avatar.time.monotonic",return_value=100):
            view.set_mode("speaking")
            view.set_mode("listening",10)
        self.assertTrue(view.dialogue_visible(108))
        with patch("capri.desktop.avatar.time.monotonic",return_value=110):
            view.set_mode("idle")
            self.assertFalse(view.dialogue_visible())

    def test_hidden_panel_leaves_no_pixels_below_figure(self):
        view = self.avatar
        view.set_subtitle("An answer")
        view.render()
        self.assertTrue(all(view.frame.pixelColor(170,y).alpha()==0 for y in range(FIG_H,500)))
        view.set_mode("listening")
        view.render()
        self.assertGreater(view.frame.pixelColor(170,420).alpha(),0)
        view.set_mode("thinking")
        view.render()
        self.assertGreater(view.frame.pixelColor(170,420).alpha(),0)

    def test_clearing_reply_hides_idle_panel_immediately(self):
        view = self.avatar
        view.set_mode("speaking")
        view.set_mode("idle")
        self.assertTrue(view.dialogue_visible())
        view.set_subtitle("")
        self.assertFalse(view.dialogue_visible())

    def test_cursor_updates_at_16ms_without_moving_the_real_mouse(self):
        view = self.avatar
        view.play_anim("spin")
        view.tele_target = QPoint(0,0)
        with patch("capri.desktop.window_companion.QCursor.pos",return_value=QPoint(90,80)):
            self.life.ride_cursor()
            self.assertEqual(view.pos(),QPoint(108,98))
            self.assertEqual(self.life.timer.interval(),16)
            self.assertEqual(self.life.timer.timerType(),Qt.TimerType.PreciseTimer)
        self.assertIsNone(view.anim)
        self.assertIsNone(view.tele_target)
        with patch("capri.desktop.window_companion.QCursor.pos",return_value=QPoint(110,100)):
            self.life.tick()
            self.assertEqual(view.pos(),QPoint(128,118))
        self.life.detach()
        self.assertEqual(self.life.timer.interval(),120)

    def test_cursor_does_not_skip_rendering_for_artificial_lag_or_start_spin(self):
        self.life.cursor = True
        self.avatar.next_spin = 0
        self.avatar.roam_img = None
        self.avatar.lag = 20
        with patch.object(self.avatar,"render") as render:
            self.avatar.tick()
        render.assert_called_once()
        self.assertIsNone(self.avatar.anim)

    def test_perch_contact_is_on_window_edge_at_every_scale(self):
        view = self.avatar
        surface = Surface("test","Test window",100,410,700,700)
        self.life.surfaces = [surface]
        for factor in (.5,1.,1.6):
            self.life.detach()
            view.set_scale(factor)
            anchor = view.seat_anchor()
            self.assertAlmostEqual(anchor.y()/view.scale_factor, FIG_H-W+W*.79)
            view.move(round(300-anchor.x()),round(surface.top-anchor.y()-15))
            self.life.drop()
            self.assertTrue(view.perched)
            self.assertAlmostEqual(view.y()+view.seat_anchor().y(),surface.top,delta=.51)
            view.set_mode("thinking")
            self.assertIsNone(view.anim)
            with patch("capri.desktop.avatar.time.time",return_value=100):
                self.assertEqual(view._figure(),view.anims["desktop_perch"][int(time.time()*8)%16])
            self.life.surfaces = [Surface("test","Test window",150,450,750,740)]
            self.life.tick()
            self.assertAlmostEqual(view.y()+view.seat_anchor().y(),450,delta=.51)
            self.life.surfaces = [surface]

    def test_flight_bobs_and_never_loads_walking_frames(self):
        view = self.avatar
        self.assertNotIn("walk",view.anims)
        view.start_roam()
        view.state = "visible"
        view.roam_last = 100
        view.flight_phase = 0
        first_y = view.y()
        view._roam_step(100.1)
        self.assertNotEqual(first_y,view.y())
        self.assertEqual(view._figure(),view.roam_img)
