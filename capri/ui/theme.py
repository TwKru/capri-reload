"""Единое оформление окон, диалогов и меню Капри."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QWidget,
)

from capri.core.paths import RESOURCE_ROOT

STYLE = """
QWidget { color: #e8ecf0; font-family: 'Consolas', 'Segoe UI'; font-size: 10pt; }
QLabel { background: transparent; }
QLabel:disabled { color: #687582; }
QWidget#capriTitleBar { background: transparent; }
QLabel#capriWindowTitle { color: #3ad6eb; font-size: 10pt; font-weight: bold; }
QToolButton#capriClose { color: #e82440; border: 1px solid #633044; background: #1a101b; padding: 0; }
QToolButton#capriClose:hover { color: #090b0f; background: #e82440; }
QLineEdit, QTextEdit, QPlainTextEdit, QTreeWidget, QTreeView, QTableView, QListView, QSpinBox, QDoubleSpinBox {
    background: #101820; color: #e8ecf0; border: 1px solid #344552;
    padding: 6px; selection-background-color: #19546a; selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTreeWidget:focus { border-color: #3ad6eb; }
QLineEdit:disabled { color: #697581; background: #0d1117; border-color: #242c36; }
QPushButton { background: #121e29; border: 1px solid #3ad6eb; color: #e8ecf0; padding: 7px 14px; }
QPushButton:hover { background: #1b3a48; border-color: #75ebf8; }
QPushButton:pressed { background: #19546a; }
QPushButton:default { border: 2px solid #e82440; padding: 6px 13px; }
QPushButton:focus { border-color: #e82440; }
QPushButton:disabled { background: #10151c; border-color: #34404a; color: #64717e; }
QToolButton { background: #14212c; border: 1px solid #344552; padding: 4px; }
QToolButton:hover, QToolButton:checked { background: #19546a; border-color: #3ad6eb; }
QComboBox { background: #101820; border: 1px solid #344552; padding: 6px 28px 6px 8px; }
QComboBox:focus, QComboBox:hover { border-color: #3ad6eb; }
QComboBox:disabled { color: #697581; border-color: #242c36; }
QComboBox::drop-down { width: 22px; border-left: 1px solid #344552; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 12px; height: 8px; }
QComboBox QAbstractItemView { background: #101820; border: 1px solid #3ad6eb; selection-background-color: #19546a; }
QTabWidget::pane { border: 1px solid #344552; background: #0d131b; }
QTabBar::tab { background: #101820; color: #91a2b1; padding: 8px 16px; border: 1px solid #263540; }
QTabBar::tab:selected { color: #3ad6eb; background: #142531; border-bottom: 2px solid #e82440; }
QTabBar::tab:hover { color: #e8ecf0; }
QTreeWidget { alternate-background-color: #14202b; }
QTreeWidget::item { padding: 5px; }
QTreeWidget::item:selected { background: #19546a; color: #ffffff; }
QHeaderView::section { background: #14212c; color: #3ad6eb; border: 0; border-bottom: 1px solid #344552; padding: 7px; }
QHeaderView, QTableCornerButton::section { background: #14212c; }
QRadioButton, QCheckBox { spacing: 8px; background: transparent; }
QRadioButton::indicator, QCheckBox::indicator { width: 14px; height: 14px; background: #101820; border: 1px solid #547082; }
QRadioButton::indicator { border-radius: 7px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked { background: #3ad6eb; border: 3px solid #142531; }
QRadioButton::indicator:hover, QCheckBox::indicator:hover { border-color: #e82440; }
QSlider::groove:horizontal { height: 5px; background: #263540; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #3ad6eb; border: 1px solid #75ebf8; }
QSlider::handle:horizontal:hover { background: #e82440; border-color: #ff6680; }
QSlider::sub-page:horizontal { background: #19617a; }
QScrollBar:vertical { background: #101820; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #345363; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #101820; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #345363; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu { background: #090f17; color: #e8ecf0; border: 1px solid #3ad6eb; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; }
QMenu::item:selected { background: #153444; color: #3ad6eb; }
QMenu::item:disabled { color: #64717e; }
QMenu::separator { height: 1px; background: #344552; margin: 5px 8px; }
QToolTip { color: #e8ecf0; background: #101820; border: 1px solid #3ad6eb; padding: 6px; }
QSizeGrip { background: transparent; }
""".replace("@CHEVRON@", (RESOURCE_ROOT / "assets/ui/chevron-down.svg").as_posix())


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("capriTitleBar")
        self.drag_offset = None
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 4, 9, 4)
        self.title = QLabel("CAPRI", self)
        self.title.setObjectName("capriWindowTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("capriClose")
        self.close_button.setText("×")
        self.close_button.setToolTip("Закрыть")
        self.close_button.setAccessibleName("Закрыть окно")
        self.close_button.setFixedSize(28, 26)
        self.close_button.clicked.connect(window.close)
        row.addWidget(self.title, 1)
        row.addWidget(self.close_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None


class CyberFrame:
    def _init_frame(self):
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setContentsMargins(10, 48, 10, 12)
        self.setMinimumWidth(380)
        self.setStyleSheet(STYLE)
        self.title_bar = TitleBar(self)
        self.windowTitleChanged.connect(self._update_title)
        self._update_title(self.windowTitle())

    def _update_title(self, title):
        label = title.removeprefix("Капри — ").removeprefix("Капри —").strip() or "Капри"
        self.title_bar.title.setText("CAPRI // " + label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.setGeometry(1, 1, self.width() - 2, 42)
            self.title_bar.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        # Стандартные Qt input/message dialogs заново вычисляют фиксированный размер при показе.
        if self.width() < 380:
            self.setMaximumWidth(max(380, self.maximumWidth()))
            self.setMinimumWidth(380)
            self.resize(380, self.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width() - 1, self.height() - 1
        outline = QPolygonF([QPointF(14, 1), QPointF(w, 1), QPointF(w, h - 14),
                            QPointF(w - 14, h), QPointF(1, h), QPointF(1, 14)])
        painter.setBrush(QColor(getattr(self,"frame_background","#090f17")))
        painter.setPen(QPen(QColor(getattr(self,"frame_accent","#3ad6eb")), 1.4))
        painter.drawPolygon(outline)
        painter.setPen(QPen(QColor("#263e4d"), 1))
        painter.drawLine(12, 43, w - 12, 43)
        painter.fillRect(16, 42, min(64, w - 30), 3, QColor("#e82440"))
        painter.end()


class CyberDialog(CyberFrame, QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_frame()


class CyberInputDialog(CyberFrame, QInputDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_frame()
        self.setOkButtonText("Отправить")
        self.setCancelButtonText("Отмена")

    @staticmethod
    def getText(parent, title, label, echo=QLineEdit.EchoMode.Normal, text="", **kwargs):
        dialog = CyberInputDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextEchoMode(echo)
        dialog.setTextValue(text)
        accepted = bool(dialog.exec())
        value = dialog.textValue()
        dialog.deleteLater()
        return value, accepted


class CyberMessageBox(CyberFrame, QMessageBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_frame()
        self.setTextFormat(Qt.TextFormat.PlainText)

    @staticmethod
    def warning(parent, title, text):
        return CyberMessageBox(QMessageBox.Icon.Warning, title, text, QMessageBox.StandardButton.Ok, parent).exec()

    @staticmethod
    def information(parent, title, text):
        return CyberMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, parent).exec()


class CyberFileDialog(CyberFrame, QFileDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self._init_frame()
        self.setLabelText(QFileDialog.DialogLabel.Accept, "Открыть")
        self.setLabelText(QFileDialog.DialogLabel.Reject, "Отмена")

    @staticmethod
    def getOpenFileName(parent, caption, directory="", filter=""):
        dialog = CyberFileDialog(parent, caption, directory, filter)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        accepted = bool(dialog.exec())
        paths, selected = dialog.selectedFiles(), dialog.selectedNameFilter()
        dialog.deleteLater()
        return (paths[0] if accepted and paths else ""), selected


def apply_theme(app):
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
