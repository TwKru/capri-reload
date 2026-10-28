"""Разрезать готовые листы 4×4 на кадры проекта без изменения рисунка персонажа."""
import argparse
import json
import os
from pathlib import Path
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def import_sheet(source, name, base):
    image = QImage(str(source))
    if image.isNull():
        raise ValueError("Не удалось открыть лист кадров")
    output = base / "assets" / "anim" / name
    output.mkdir(parents=True, exist_ok=True)
    for index in range(16):
        row, column = divmod(index, 4)
        left, right = round(column * image.width() / 4), round((column + 1) * image.width() / 4)
        top, bottom = round(row * image.height() / 4), round((row + 1) * image.height() / 4)
        cell = image.copy(left, top, right - left, bottom - top)
        cell = cell.scaled(280, 350, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        frame = QImage(340, 380, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.drawImage((340 - cell.width()) // 2, 376 - cell.height(), cell)
        painter.end()
        if not frame.save(str(output / f"{index:04d}.png")):
            raise OSError("Не удалось сохранить кадр")
    metadata = {"fps": 60, "inbetweens": 6, "loop": True}
    if name == "walk":
        metadata["mirror_keys"] = [4, 5, 6, 7]
    (output / "motion.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    originals = base / "assets" / "motion_sources"
    originals.mkdir(exist_ok=True)
    shutil.copy2(source, originals / (name + ".png"))
    print(name, "16 drawn poses, 96 playback frames, 60 fps")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("walk", type=Path)
    parser.add_argument("spin", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    import_sheet(args.walk, "walk", root)
    import_sheet(args.spin, "spin", root)
