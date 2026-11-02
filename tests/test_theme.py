"""Общая тема не перекрывает поля, закрытие не сохраняет настройки."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

import main
from ai_dialog import AIDialog
from profile_dialog import ProfileDialog
from sound_dialog import SoundDialog
from entries_dialog import EntriesDialog, SiteForm, ReplyForm
from theme import CyberFileDialog, CyberInputDialog, CyberMessageBox, apply_theme


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families():
            for filename in ("consola.ttf", "consolab.ttf", "consolai.ttf"):
                path = Path("C:/Windows/Fonts") / filename
                if path.exists():
                    QFontDatabase.addApplicationFont(str(path))
        apply_theme(cls.app)

    def make_capri(self):
        capri = Mock(cfg=main.DEFAULTS.copy(), listener=None)
        capri.current_mic.return_value = "Микрофон Windows"
        return capri

    def test_all_dialogs_keep_header_separate_from_editable_fields(self):
        capri = self.make_capri()
        actions = Mock(sites={}, apps={}, replies={})
        windows = [AIDialog(capri), ProfileDialog(capri), SoundDialog(capri), EntriesDialog(actions),
                   SiteForm(None), ReplyForm(None), CyberInputDialog(), CyberMessageBox(), CyberFileDialog()]
        for window in windows:
            with self.subTest(type=type(window).__name__):
                self.addCleanup(window.close)
                window.show()
                self.app.processEvents()
                self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
                self.assertGreaterEqual(window.width(), 380)
                self.assertTrue(window.rect().contains(window.title_bar.geometry()))
                for field in window.findChildren(QLineEdit):
                    if field.isVisible():
                        top = field.mapTo(window, field.rect().topLeft()).y()
                        self.assertGreater(top, window.title_bar.geometry().bottom())
                window.close()

    def test_header_close_cancels_without_saving_api_key(self):
        capri = self.make_capri()
        window = AIDialog(capri)
        self.addCleanup(window.close)
        window.key.setText("not-a-real-key")
        window.show()
        QTest.mouseClick(window.title_bar.close_button, Qt.MouseButton.LeftButton)
        self.assertFalse(window.isVisible())
        capri.set_ai_settings.assert_not_called()

    def test_sound_timer_stops_when_dialog_is_rejected(self):
        window = SoundDialog(self.make_capri())
        self.addCleanup(window.close)
        self.assertTrue(window.timer.isActive())
        window.reject()
        self.assertFalse(window.timer.isActive())

    def test_input_factory_preserves_cancel_and_initial_value(self):
        with patch.object(CyberInputDialog, "exec", return_value=0):
            value, accepted = CyberInputDialog.getText(None, "Запрос", "Текст:", text="Исходный запрос")
        self.assertEqual(value, "Исходный запрос")
        self.assertFalse(accepted)

    def test_file_picker_returns_selected_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.exe"
            path.write_bytes(b"test")
            def accept(dialog):
                dialog.selectFile(str(path))
                return 1
            with patch.object(CyberFileDialog, "exec", accept):
                selected, _ = CyberFileDialog.getOpenFileName(None, "Программа", folder, "Программы (*.exe)")
            self.assertEqual(Path(selected), path)
