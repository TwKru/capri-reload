"""Ограниченный кэш кадров, повторное использование текста и совместный синтез фразы."""
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QStaticText  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from capri.audio import voice_service as voice  # noqa: E402
from capri.desktop import avatar  # noqa: E402


class RenderCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_animation_frames_load_lazily_and_memory_stays_bounded(self):
        paths = []
        for index in range(20):
            image = QImage(20, 20, avatar.FMT)
            image.fill(QColor(index * 10, 0, 0))
            path = self.root / f"{index:03}.png"
            image.save(str(path))
            paths.append(str(path))
        frames = avatar.AnimationFrames(paths)
        self.assertEqual(len(frames), 20)
        self.assertEqual(len(frames.cache), 0)
        first = frames[0]
        self.assertEqual(first.cacheKey(), frames[0].cacheKey())
        for index in range(20):
            frames[index]
        self.assertLessEqual(len(frames.cache), 8)
        self.assertNotIn(0, frames.cache)
        self.assertEqual(frames[0], first)
        with self.assertRaises(IndexError):
            frames[20]

    def test_invalid_png_does_not_break_animation_index(self):
        folder = self.root / "wave"
        folder.mkdir()
        (folder / "broken.png").write_bytes(b"invalid")
        self.assertEqual(avatar.load_anims(str(self.root)), {})

    def test_subtitle_layout_is_reused_and_refreshes_on_text_change(self):
        with patch("capri.desktop.avatar.load_anims", return_value={}):
            view = avatar.Avatar(str(self.root))
        self.addCleanup(view.close)
        self.addCleanup(view.overlay.close)
        rect = QRectF(16, 410, 308, 74)
        view.set_subtitle("Длинный ответ. " * 200)
        with patch("capri.desktop.avatar.QStaticText", wraps=QStaticText) as layout:
            font, text = view._prepare_subtitle(rect)
            count = layout.call_count
            for _ in range(20):
                self.assertIs(view._prepare_subtitle(rect)[1], text)
            self.assertEqual(layout.call_count, count)
            self.assertLessEqual(text.size().height(), rect.height())
            self.assertTrue(text.text().endswith("…"))
            view.set_subtitle("Новый ответ.")
            self.assertIsNot(view._prepare_subtitle(rect)[1], text)
            self.assertGreater(layout.call_count, count)
        self.assertEqual(view.subtitle, "Новый ответ.")

    def test_dialogue_keeps_question_and_treats_reply_markup_as_plain_text(self):
        view = avatar.Avatar(str(self.root))
        self.addCleanup(view.close)
        self.addCleanup(view.overlay.close)
        view.set_subtitle("> Как вывести <b> в тексте?")
        view.set_subtitle('Напиши <b>пример</b> & "кавычки".')
        self.assertEqual(view.dialogue_request, "Как вывести <b> в тексте?")
        rect = QRectF(30, 422, 286, 65)
        font, text = view._prepare_subtitle(rect, dialogue=True)
        self.assertIn("CAPRI:", text.text())
        self.assertIn("&lt;b&gt;пример&lt;/b&gt;", text.text())
        self.assertIn("&amp;", text.text())
        self.assertIs(view._prepare_subtitle(rect, dialogue=True)[1], text)
        self.assertLessEqual(text.size().height(), rect.height())
        self.assertEqual(view.subtitle, 'Напиши <b>пример</b> & "кавычки".')

    def test_dialogue_thinking_does_not_repeat_user_command_as_answer(self):
        view = avatar.Avatar(str(self.root))
        self.addCleanup(view.close)
        self.addCleanup(view.overlay.close)
        view.set_subtitle("> Открой браузер")
        view.mode = "thinking"
        rect = QRectF(30, 422, 286, 65)
        _, text = view._prepare_subtitle(rect, dialogue=True)
        self.assertIn("Думаю", text.text())
        self.assertNotIn("Открой браузер", text.text())
        view.mode = "listening"
        self.assertIn("Слушаю", view._prepare_subtitle(rect, dialogue=True)[1].text())


class SharedSpeechTests(unittest.TestCase):
    def test_concurrent_requests_for_same_phrase_synthesize_once(self):
        with tempfile.TemporaryDirectory() as folder, patch("capri.audio.voice_service.TTS_CACHE", folder):
            speaker = voice.Speaker({})
            entered, release = threading.Event(), threading.Event()
            def render(text, destination):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError()
                Path(destination).write_bytes(b"complete audio")
                return destination
            with patch.object(speaker, "render", side_effect=render) as synthesize, ThreadPoolExecutor(3) as pool:
                pending = [pool.submit(speaker.cached_render, "Одинаковая фраза", str(Path(folder) / f"{i}.wav"))
                           for i in range(3)]
                self.assertTrue(entered.wait(2))
                release.set()
                paths = [result.result(timeout=3) for result in pending]
            synthesize.assert_called_once()
            for path in paths:
                self.assertEqual(Path(path).read_bytes(), b"complete audio")

    def test_cache_cleanup_does_not_remove_in_progress_synthesis(self):
        with tempfile.TemporaryDirectory() as folder, patch("capri.audio.voice_service.TTS_CACHE", folder), \
                patch("capri.audio.voice_service.CACHE_MAX_FILES", 1):
            staging = Path(folder) / "in-progress.tmp"
            staging.write_bytes(b"partial")
            for index in range(4):
                (Path(folder) / f"{index}.wav").write_bytes(b"audio")
            voice._trim_cache()
            self.assertEqual(staging.read_bytes(), b"partial")
            self.assertEqual(len(list(Path(folder).glob("*.wav"))), 1)


if __name__ == "__main__":
    unittest.main()
