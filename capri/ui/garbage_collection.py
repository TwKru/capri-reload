"""Collect Python reference cycles on the Qt GUI thread."""
import gc

from PySide6.QtCore import QObject, QTimer, Slot


class GuiGarbageCollector(QObject):
    """Prevent a worker's allocations from deleting Qt wrappers mid-paint."""

    def __init__(self, parent):
        super().__init__(parent)
        self.was_enabled = gc.isenabled()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.collect)
        self.timer.start()

    @Slot()
    def collect(self):
        gc.collect()

    def close(self):
        """Restore the caller's policy after the GUI event loop has ended."""
        self.timer.stop()
        if self.was_enabled:
            gc.enable()
