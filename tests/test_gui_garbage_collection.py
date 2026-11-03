import gc
import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from capri.ui.garbage_collection import GuiGarbageCollector


class GuiGarbageCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_allocations_do_not_collect_gui_cycles(self):
        original = gc.isenabled()
        gc.enable()
        collector = GuiGarbageCollector(self.app)
        finalized = []

        class Cycle:
            def __init__(self):
                self.cycle = self

            def __del__(self):
                finalized.append(threading.get_ident())

        obj = Cycle()
        del obj

        def allocate():
            for _ in range(10000):
                Cycle()

        try:
            thread = threading.Thread(target=allocate)
            thread.start()
            thread.join()
            self.assertEqual(finalized, [])
            loop = QEventLoop()
            collector.timer.setInterval(1)
            QTimer.singleShot(30, loop.quit)
            loop.exec()
            self.assertTrue(finalized)
            self.assertEqual(set(finalized), {threading.get_ident()})
        finally:
            collector.close()
            gc.enable() if original else gc.disable()
        self.assertFalse(collector.timer.isActive())

    def test_preserves_preexisting_disabled_policy(self):
        original = gc.isenabled()
        gc.disable()
        try:
            collector = GuiGarbageCollector(self.app)
            collector.close()
            self.assertFalse(gc.isenabled())
        finally:
            gc.enable() if original else gc.disable()
