"""В игре нет прозрачных окон и фонового прогрева; команды и голос остаются доступны."""
import copy
import io
import json
import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from avatar import Avatar  # noqa: E402
from game_mode import covers_monitor  # noqa: E402
from local_ai import LocalAI  # noqa: E402
import main  # noqa: E402
import voice  # noqa: E402


class FullscreenTests(unittest.TestCase):
    def test_other_monitor_and_borderless_frames(self):
        self.assertTrue(covers_monitor((1920, 0, 4480, 1440), (1920, 0, 4480, 1440)))
        self.assertTrue(covers_monitor((-8, -8, 1928, 1088), (0, 0, 1920, 1080)))
        self.assertFalse(covers_monitor((0, 0, 1920, 1040), (0, 0, 1920, 1080)))
        self.assertFalse(covers_monitor((50, 50, 1200, 800), (0, 0, 1920, 1080)))


class AvatarGamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("avatar.load_anims", return_value={}):
            self.avatar = Avatar(os.path.join(main.BASE, "assets"))
        self.addCleanup(self.avatar.overlay.close)
        self.addCleanup(self.avatar.close)

    def test_game_mode_blocks_summon_roam_and_lightning(self):
        self.avatar.set_game_mode(True)
        with patch.object(self.avatar.overlay, "strike") as strike:
            self.avatar.summon()
            self.avatar.start_roam()
            self.avatar.start_hopping()
            self.avatar.set_mode("speaking")
            self.assertFalse(self.avatar.isVisible())
            self.assertFalse(self.avatar.timer.isActive())
            self.assertFalse(self.avatar.overlay.timer.isActive())
            self.assertFalse(self.avatar.hopping)
        strike.assert_not_called()

    def test_entering_game_hides_existing_windows_and_normal_mode_can_resume(self):
        with patch.object(self.avatar, "raise_"):
            self.avatar.summon()
        self.assertTrue(self.avatar.timer.isActive())
        self.avatar.set_game_mode(True)
        self.assertFalse(self.avatar.isVisible())
        self.assertFalse(self.avatar.timer.isActive())
        self.avatar.set_game_mode(False)
        with patch.object(self.avatar, "raise_"):
            self.avatar.summon()
        self.assertTrue(self.avatar.timer.isActive())
        self.assertEqual(self.avatar.state, "appearing")

    def test_hidden_avatar_has_no_animation_timer(self):
        self.assertFalse(self.avatar.timer.isActive())
        self.avatar.state, self.avatar.k = "vanishing", 100
        self.avatar.timer.start(33)
        self.avatar.tick()
        self.assertFalse(self.avatar.timer.isActive())


class GamingResourceTests(unittest.TestCase):
    def test_game_chat_uses_cpu_in_both_response_modes(self):
        ai = LocalAI({})
        ai.game_mode = True
        with patch("local_ai._post", return_value={"message": {"content": "OK."}}) as request:
            ai._chat([{"role": "user", "content": "Hello"}])
        self.assertEqual(request.call_args.args[1]["options"]["num_gpu"], 0)
        self.assertEqual(request.call_args.args[1]["options"]["num_thread"], 2)
        data = json.dumps({"message": {"content": "OK."}, "done": True}).encode() + b"\n"
        with patch("local_ai.urllib.request.urlopen", return_value=io.BytesIO(data)) as request:
            ai._chat_stream([{"role": "user", "content": "Hello"}], lambda text: None)
        self.assertEqual(json.loads(request.call_args.args[0].data)["options"]["num_gpu"], 0)

    def test_game_startup_does_not_preload_big_model(self):
        ai = LocalAI({})
        ai.game_mode = True
        with patch.object(ai, "installed", return_value=[ai.model]), patch("local_ai._post") as request:
            ai.start_server()
        request.assert_not_called()

    def test_prefetch_stops_but_foreground_speech_still_works(self):
        speaker = voice.Speaker({})
        speaker.background_paused = True
        with patch.object(speaker, "render") as render:
            self.assertFalse(speaker.prepare("Фоновая фраза"))
        render.assert_not_called()
        with patch.object(speaker, "_edge", return_value=False) as speech:
            speaker.say("Голосовая команда")
        speech.assert_called_once()

    def test_memory_release_waits_for_active_chat_and_runs_once(self):
        cfg = copy.deepcopy(main.DEFAULTS)
        cfg.update(local_ai=False, intent_router=False)
        with patch.object(main, "Actions"), patch.object(main, "AI"), patch.object(main, "make_glitch_sound"):
            capri = main.Capri(cfg)
        capri.local = Mock()
        done = threading.Event()
        capri.local.release_memory.side_effect = done.set
        capri.ai_call_lock.acquire()
        capri.set_game_mode(True)
        capri.local.release_memory.assert_not_called()
        capri.ai_call_lock.release()
        capri.set_game_mode(True)
        self.assertTrue(done.wait(2))
        self.assertTrue(capri.ai_call_lock.acquire(timeout=2))
        capri.ai_call_lock.release()
        capri.set_game_mode(True)
        capri.local.release_memory.assert_called_once()
        self.assertTrue(capri.speaker.background_paused)
        capri.set_game_mode(False)
        self.assertFalse(capri.speaker.background_paused)
        self.assertFalse(capri.local.game_mode)


if __name__ == "__main__":
    unittest.main()
