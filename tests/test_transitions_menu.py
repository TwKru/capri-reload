"""Заставки завершаются один раз, а меню управляет теми же обработчиками."""
import os
import copy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from transitions import ScreenTransition, chip_icon
from control_menu import build_control_menu


class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ScreenTransition()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.timer.stop)
        self.view.resize(960, 540)
        self.view.head_center = QPointF(480, 270)

    def frame(self, mode, seconds):
        image = QImage(self.view.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        self.view.draw_frame(painter, mode, seconds)
        painter.end()
        return image

    def test_startup_fills_entire_screen_then_reveals_desktop(self):
        covered = self.frame("startup", 2.)
        for x, y in ((0, 0), (959, 0), (0, 539), (959, 539), (480, 270)):
            self.assertEqual(covered.pixelColor(x, y), QColor("#ff224c"))
        clear = self.frame("startup", 3.59)
        for x, y in ((0, 0), (959, 539), (480, 270)):
            self.assertEqual(clear.pixelColor(x, y).alpha(), 0)

    def test_shutdown_avatar_falls_below_screen(self):
        self.view.outgoing = QImage(340, 380, QImage.Format.Format_ARGB32_Premultiplied)
        self.view.outgoing.fill(QColor("#00ff00"))
        self.view.outgoing_pos = QPointF(10, 10)
        self.assertEqual(self.frame("shutdown", 0).pixelColor(40, 40), QColor("#00ff00"))
        self.assertEqual(self.frame("shutdown", 2.59).pixelColor(40, 40).alpha(), 0)

    def test_finished_emitted_once_and_timer_stops(self):
        events = []
        self.view.finished.connect(events.append)
        self.view.elapsed = Mock()
        self.view.play("startup")
        self.view.elapsed.elapsed.return_value = 4000
        self.view._tick()
        self.view._tick()
        self.assertEqual(events, ["startup"])
        self.assertFalse(self.view.timer.isActive())
        self.assertFalse(self.view.isVisible())

    def test_shutdown_supersedes_startup_without_late_start_event(self):
        events = []
        self.view.finished.connect(events.append)
        self.view.elapsed = Mock()
        self.view.play("startup")
        self.view.play("shutdown")
        self.view.elapsed.elapsed.return_value = 2700
        self.view._tick()
        self.assertEqual(events, ["shutdown"])

    def test_chip_icon_is_available_at_tray_sizes(self):
        icon = chip_icon()
        for size in (16, 24, 32, 64):
            image = icon.pixmap(size, size).toImage()
            self.assertFalse(image.isNull())
            self.assertTrue(any(image.pixelColor(x, y).alpha() for x in range(size) for y in range(size)))


class ControlMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.capri = Mock(cfg={"voice_volume": 74}, voice_paused=False, last_request="вопрос")
        self.capri.actions.sites = {"ютуб": "https://youtube.com"}
        self.capri.actions.apps = {"блокнот": "notepad.exe"}
        self.avatar = Mock()
        self.handlers = {key: Mock() for key in ("text", "edit", "ai", "sound", "profile", "entries", "sources", "github", "quit")}
        self.menu = build_control_menu(self.capri, self.avatar, self.handlers, Path.cwd())
        self.addCleanup(self.menu.close)

    def find(self, text, menu=None):
        for action in (menu or self.menu).actions():
            if action.text() == text:
                return action
            if action.menu():
                found = self.find(text, action.menu())
                if found:
                    return found
        return None

    def test_settings_edit_and_exit_use_original_handlers(self):
        for label, key in (("Изменить последний запрос…", "edit"), ("Нейросеть и API…", "ai"),
                           ("Голос и чувствительность…", "sound"), ("Извлечь чип и выйти", "quit")):
            self.find(label).trigger()
            self.handlers[key].assert_called_once()

    def test_microphone_menu_toggles_pause_even_while_waiting_for_name(self):
        self.menu.aboutToShow.emit()
        action = self.find("Микрофон включён — выключить")
        self.assertTrue(action.isChecked())
        action.trigger()
        self.capri.toggle_voice.assert_called_once_with("listening")
        self.capri.voice_paused = True
        self.menu.aboutToShow.emit()
        action = self.find("Микрофон на паузе — включить")
        self.assertFalse(action.isChecked())
        action.trigger()
        self.capri.toggle_voice.assert_called_with("idle")

    def test_media_and_power_keep_existing_command_confirmation_path(self):
        self.find("Следующий трек").trigger()
        self.capri.text_command.assert_called_with("следующий трек")
        self.find("Выключить компьютер…").trigger()
        self.capri.text_command.assert_called_with("выключи компьютер")

    def test_saved_sites_and_apps_remain_accessible(self):
        launch = self.find("Открыть сайт или программу").menu()
        launch.aboutToShow.emit()
        self.find("блокнот").trigger()
        self.capri.text_command.assert_called_with("открой блокнот")
        self.find("ютуб").trigger()
        self.capri.text_command.assert_called_with("открой ютуб")


class LifecycleIntegrationTests(unittest.TestCase):
    def test_main_starts_after_intro_and_all_exits_wait_for_outro(self):
        import main
        from avatar import Avatar
        app = QApplication.instance() or QApplication([])
        avatar = Avatar(str(Path(__file__).resolve().parents[1] / "assets"))
        transition = ScreenTransition()
        self.addCleanup(avatar.close)
        self.addCleanup(avatar.overlay.close)
        self.addCleanup(avatar.timer.stop)
        self.addCleanup(transition.close)
        self.addCleanup(transition.timer.stop)
        cfg = copy.deepcopy(main.DEFAULTS)
        capri = Mock(cfg=cfg, voice_paused=False, last_request="")
        capri.actions.sites, capri.actions.apps = {}, {}
        capri.listener = None
        tray = Mock()
        def event_loop():
            capri.start.assert_not_called()
            self.assertEqual(transition.mode, "startup")
            transition.finished.emit("startup")
            capri.start.assert_called_once()
            # Голосовой выход использует тот же обработчик, что пункт меню.
            quit_handler = capri.quit_app.connect.call_args.args[0]
            quit_handler()
            quit_handler()
            self.assertEqual(transition.mode, "shutdown")
            app.quit.assert_not_called()
            self.assertTrue(capri.voice_paused)
            transition.finished.emit("startup")
            capri.start.assert_called_once()
            transition.finished.emit("shutdown")
            app.quit.assert_called_once()
            self.assertIsNotNone(tray.setContextMenu.call_args_list[0].args[0])
            self.assertIsNone(tray.setContextMenu.call_args.args[0])
            return 0
        with patch.object(main, "QApplication", return_value=app), patch.object(main, "Avatar", return_value=avatar), \
                patch.object(main, "Capri", return_value=capri), patch.object(main, "ScreenTransition", return_value=transition), \
                patch.object(main, "QSystemTrayIcon", return_value=tray), patch.object(main, "load_config", return_value=cfg), \
                patch.object(app, "quit"), patch.object(app, "exec", side_effect=event_loop), \
                self.assertRaises(SystemExit) as stopped:
            main.main()
        self.assertEqual(stopped.exception.code, 0)
