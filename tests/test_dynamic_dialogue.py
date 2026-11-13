"""Growing dialogue and typewriter progression without a microphone or TTS."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from capri.desktop.avatar import FIG_H, SUBTITLE_CPS, Avatar, H, W


class DynamicDialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists("C:/Windows/Fonts/consola.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.view = Avatar(folder.name)
        self.view.state = "visible"
        self.view.next_spin = float("inf")
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.overlay.close)
        self.addCleanup(self.view.timer.stop)

    def start_answer(self, text):
        with patch("capri.desktop.avatar.time.monotonic",return_value=100):
            self.view.set_mode("thinking")
            self.view.set_subtitle("> Вопрос")
            self.view.set_subtitle(text)
            self.view.set_mode("speaking")

    def test_letters_appear_by_elapsed_time_not_frame_count(self):
        text = "Ответ постепенно появляется. "*20
        self.start_answer(text)
        self.assertEqual(self.view._dialogue_value(),"")
        self.view._advance_subtitle(100.5)
        count = int(.5*SUBTITLE_CPS)
        self.assertEqual(self.view._dialogue_value(),text[:count])
        self.view._advance_subtitle(100.5)
        self.assertEqual(len(self.view._dialogue_value()),count)
        self.assertEqual(self.view.subtitle,text)

    def test_text_waits_for_audio_playback_instead_of_synthesis(self):
        self.start_answer("Ответ постепенно появляется. "*20)
        self.view.speech_active = lambda:False
        self.view._advance_subtitle(105)
        self.assertEqual(self.view._dialogue_value(),"Думаю…")
        self.assertEqual(self.view._answer_shown,0)
        self.view.speech_active = lambda:True
        self.view._advance_subtitle(105.5)
        self.assertEqual(len(self.view._dialogue_value()),int(.5*SUBTITLE_CPS))

    def test_thinking_label_overrides_answer_while_model_is_generating(self):
        self.view.set_mode("thinking")
        self.view.set_subtitle("Ответ уже получен, голос ещё не запущен")
        self.assertEqual(self.view._dialogue_value(),"Думаю…")
        self.assertEqual(self.view.subtitle,"Ответ уже получен, голос ещё не запущен")

    def test_wait_for_next_audio_chunk_keeps_revealed_text_and_adds_status(self):
        self.start_answer("Первая часть ответа. "*20)
        self.view.speech_active = lambda:True
        self.view._advance_subtitle(101)
        shown = self.view._dialogue_value()
        self.view.speech_active = lambda:False
        self.view._advance_subtitle(104)
        self.assertEqual(self.view._dialogue_value(),shown.rstrip()+"\n\nДумаю…")
        self.assertNotIn("Думаю",self.view.subtitle)
        self.view.speech_active = lambda:True
        self.assertEqual(self.view._dialogue_value(),shown)

    def test_window_grows_during_reveal_and_stays_inside_screen(self):
        text = "Большой ответ со словами и переносами. "*200
        self.start_answer(text)
        self.view.move_to_named("bottom-right")
        heights,widths = [],[]
        for t in (101,104,108,115,150,300):
            self.view._advance_subtitle(t)
            with patch("capri.desktop.avatar.time.monotonic",return_value=t):
                self.view.render()
            heights.append(self.view.height())
            widths.append(self.view.width())
            area = self.view.screen().availableGeometry()
            self.assertTrue(area.contains(self.view.geometry()))
            self.assertEqual(self.view.frame.deviceIndependentSize().height(),self.view._dialogue_height)
        self.assertEqual(heights,sorted(heights))
        self.assertEqual(widths,sorted(widths))
        self.assertGreater(max(heights),H)
        self.assertGreater(max(widths),W)

    def test_streamed_sentences_append_and_final_response_does_not_duplicate(self):
        self.start_answer("Первая фраза.")
        self.view._advance_subtitle(101)
        self.view.set_subtitle("Вторая фраза.")
        self.assertEqual(self.view._answer_text,"Первая фраза. Вторая фраза.")
        self.view.set_subtitle("Первая фраза.\nВторая фраза.")
        self.assertEqual(self.view._answer_text,"Первая фраза. Вторая фраза.")
        self.view._advance_subtitle(self.view._typing_last+10)
        self.assertIn("Вторая фраза.",self.view._dialogue_value())

    def test_panel_stays_until_reveal_finishes_then_expires(self):
        self.start_answer("Текст. "*100)
        with patch("capri.desktop.avatar.time.monotonic",return_value=101):
            self.view.set_mode("idle")
        self.assertTrue(self.view.dialogue_visible(110))
        self.view._advance_subtitle(150)
        self.assertFalse(self.view._typing)
        self.assertTrue(self.view.dialogue_visible(154.99))
        self.assertFalse(self.view.dialogue_visible(155))

    def test_cancel_and_next_request_reset_reveal_and_size(self):
        self.start_answer("Длинный ответ. "*200)
        self.view._advance_subtitle(160)
        self.view.render()
        self.assertGreater(self.view.height(),H)
        self.view.set_subtitle("")
        self.view.set_mode("idle")
        self.view.render()
        self.assertFalse(self.view._typing)
        self.assertEqual(self.view.size().width(),W)
        self.assertEqual(self.view.size().height(),H)
        self.start_answer("Короткий ответ.")
        self.assertEqual(self.view._dialogue_value(),"")
        self.assertEqual(self.view.height(),H)

    def test_new_nonspoken_status_replaces_previous_answer(self):
        self.start_answer("Предыдущий ответ")
        self.view._advance_subtitle(110)
        self.view.set_mode("idle")
        self.view.set_subtitle("Задание остановлено")
        self.assertEqual(self.view._dialogue_value(),"Задание остановлено")

    def test_long_answer_is_scrollable_without_truncating_text(self):
        text = "Очень длинный ответ. "*1000
        self.start_answer(text)
        self.view._advance_subtitle(2000)
        self.view.render()
        self.assertEqual(self.view._dialogue_value(),text)
        self.assertGreater(self.view._dialogue_scroll_max,0)
        before = self.view._dialogue_scroll
        event = SimpleNamespace(position=lambda:QPointF(80,FIG_H+50),angleDelta=lambda:QPoint(0,120),
                                accept=Mock(),ignore=Mock())
        self.view.wheelEvent(event)
        self.assertLess(self.view._dialogue_scroll,before)
        self.assertFalse(self.view._dialogue_follow)
        event.accept.assert_called_once()

    def test_repeated_frame_reuses_dialogue_measurement(self):
        self.start_answer("Текст")
        self.view._advance_subtitle(101)
        self.view.render()
        with patch.object(self.view,"_layout_dialogue",wraps=self.view._layout_dialogue) as layout:
            for _ in range(10):
                self.view.render()
            layout.assert_not_called()

    def test_expanded_window_fits_screen_after_changing_avatar_scale(self):
        self.start_answer("Большой ответ. "*500)
        self.view._advance_subtitle(1000)
        self.view.render()
        for factor in (.5,1.,1.6):
            self.view.set_scale(factor)
            self.view.render()
            area = self.view.screen().availableGeometry()
            self.assertTrue(area.contains(self.view.geometry()))
            self.assertEqual(self.view.width(),round(self.view._dialogue_width*self.view.scale_factor))
            self.assertEqual(self.view.height(),round(self.view._dialogue_height*self.view.scale_factor))
