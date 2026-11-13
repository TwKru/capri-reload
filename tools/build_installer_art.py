"""Render branded Inno Setup bitmaps from the existing Capri sprite."""
import os
from pathlib import Path


def build():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    root = Path(__file__).resolve().parents[1]
    image = QImage(328, 628, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 328, 628)
    gradient.setColorAt(0, QColor("#2a193b"))
    gradient.setColorAt(1, QColor("#142332"))
    painter.fillRect(image.rect(), gradient)
    painter.setPen(QColor("#f3eefb"))
    painter.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
    painter.drawText(QRect(30, 40, 270, 65), Qt.AlignmentFlag.AlignLeft, "CAPRI")
    painter.setPen(QColor("#bca8db"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(QRect(30, 115, 260, 50), Qt.TextFlag.TextWordWrap, "Твоя цифровая спутница")
    character = QImage(str(root / "assets/poses/capri_answer.png"))
    character = character.scaled(300, 340, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
    painter.drawImage((328 - character.width()) // 2, 190, character)
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(QRect(30, 560, 280, 45), Qt.TextFlag.TextWordWrap, "ГОЛОС · ХАРАКТЕР · ИИ")
    painter.end()
    image.save(str(root / "assets/ui/installer-banner.bmp"))
    small = QImage(110, 110, QImage.Format.Format_RGB32)
    small.fill(QColor("#1c1728"))
    painter = QPainter(small)
    painter.setPen(QColor("#bd91fa"))
    painter.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
    painter.drawText(small.rect(), Qt.AlignmentFlag.AlignCenter, "C")
    painter.end()
    small.save(str(root / "assets/ui/installer-mark.bmp"))
    app.processEvents()


if __name__ == "__main__":
    build()
