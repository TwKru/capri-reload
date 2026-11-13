"""Graphical first-run setup: local GGUF download or a cloud API, without a terminal."""
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capri.ai.providers.llama_cpp import CATALOG, install
from capri.app.setup_service import API_PROVIDERS, api_settings, local_settings, save_setup
from capri.core import cancellation
from capri.core.paths import APP_ROOT, RESOURCE_ROOT

STYLE = """
QDialog { background:#101018; color:#f3eefb; }
QWidget { color:#f3eefb; font-family:'Segoe UI'; font-size:14px; }
QLabel { background:transparent; border:0; }
QFrame#brand { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #2a193b,stop:1 #142332); border-radius:18px; }
QLabel#wordmark { font-size:34px; font-weight:800; letter-spacing:5px; }
QLabel#eyebrow { color:#b8a4df; font-size:11px; font-weight:700; letter-spacing:2px; }
QLabel#heading { font-size:28px; font-weight:700; }
QLabel#subheading { font-size:15px; color:#aba6bc; }
QLabel#muted { color:#a8a3ba; font-size:13px; }
QLabel#step { color:#aaa2b9; padding:9px 0; font-size:13px; }
QLabel#step[active="true"] { color:#f4efff; font-weight:700; }
QLabel#error { color:#ffb2c1; }
QRadioButton { padding:19px; background:#1b1a27; border:1px solid #383244; border-radius:12px; font-size:16px; }
QRadioButton:checked { border:2px solid #bb8aff; background:#282037; padding:18px; }
QRadioButton::indicator { width:18px; height:18px; border:2px solid #776c8a; border-radius:10px; background:#121019; }
QRadioButton::indicator:checked { background:#bb8aff; border:2px solid #e3ccff; }
QLineEdit,QComboBox { background:#1c1b29; border:1px solid #484056; border-radius:9px; padding:12px; min-height:22px; selection-background-color:#735598; }
QLineEdit:focus,QComboBox:focus { border:1px solid #c39bff; }
QComboBox QAbstractItemView { background:#222033; selection-background-color:#674a8d; color:white; }
QCheckBox { spacing:9px; color:#bcb5cc; }
QPushButton { background:#242130; border:1px solid #443c53; border-radius:9px; padding:11px 20px; font-weight:600; }
QPushButton:hover { background:#342b43; }
QPushButton#primary { background:#bb8aff; color:#171020; border:0; }
QPushButton#primary:hover { background:#d2afff; }
QPushButton:disabled { background:#272431; color:#777084; }
QProgressBar { background:#242031; border:0; border-radius:5px; height:9px; text-align:center; }
QProgressBar::chunk { background:#bd91fa; border-radius:5px; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


class ModelDownload(QThread):
    progress = Signal(str)
    success = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, base, model, parent=None):
        super().__init__(parent)
        self.base, self.model = base, model
        self.scope = cancellation.Scope()

    def run(self):
        try:
            with self.scope.bind():
                files = install(self.base, self.model, progress=self.progress.emit)
                self.scope.checkpoint()
                self.success.emit(local_settings(files))
        except cancellation.RequestCancelled:
            self.cancelled.emit()
        except Exception:
            self.failed.emit("Не удалось загрузить модель. Проверьте подключение к интернету и свободное место, затем попробуйте ещё раз.")


class SetupWizard(QDialog):
    def __init__(self, cfg, config_path=None, base=APP_ROOT, initial_mode=None):
        super().__init__()
        self.cfg, self.base = cfg, Path(base)
        self.config_path = Path(config_path or self.base / "config.json")
        self.worker = None
        self.pending_settings = None
        self.closing = False
        self.setWindowTitle("Капри — знакомство и настройка")
        self.setMinimumSize(860, 630)
        self.resize(900, 660)
        self.setStyleSheet(STYLE)
        shell = QHBoxLayout(self)
        shell.setContentsMargins(18, 18, 18, 18)
        shell.setSpacing(30)
        brand = QFrame()
        brand.setObjectName("brand")
        brand.setFixedWidth(255)
        left = QVBoxLayout(brand)
        left.setContentsMargins(25, 28, 25, 24)
        left.addWidget(label("ТВОЯ ЦИФРОВАЯ СПУТНИЦА", "eyebrow"))
        left.addWidget(label("CAPRI", "wordmark"))
        left.addWidget(label("Немного характера.\nМного возможностей.", "muted"))
        portrait = QLabel()
        image = QPixmap(str(RESOURCE_ROOT / "assets/poses/capri_answer.png"))
        portrait.setPixmap(image.scaled(205, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(portrait, 1)
        self.steps = []
        for title in ("01   Как будем общаться", "02   Подключение", "03   Всё готово"):
            step = label(title, "step")
            self.steps.append(step)
            left.addWidget(step)
        left.addSpacing(10)
        left.addWidget(label("Голос и команды работают\nпрямо на компьютере.", "muted"))
        shell.addWidget(brand)
        right = QVBoxLayout()
        right.setContentsMargins(0, 15, 14, 10)
        right.setSpacing(16)
        self.heading = label("Познакомимся?", "heading")
        self.subtitle = label("Выбери, как Капри будет отвечать на твои вопросы.", "subheading")
        right.addWidget(self.heading)
        right.addWidget(self.subtitle)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        self._choice_page()
        self._settings_page()
        self._ready_page()
        self.error = label("", "error")
        right.addWidget(self.error)
        buttons = QHBoxLayout()
        self.back = QPushButton("Назад")
        self.back.clicked.connect(self.previous)
        buttons.addWidget(self.back)
        buttons.addStretch()
        self.next = QPushButton("Продолжить  →")
        self.next.setObjectName("primary")
        self.next.clicked.connect(self.advance)
        buttons.addWidget(self.next)
        right.addLayout(buttons)
        shell.addLayout(right, 1)
        self.change_page(0)
        if initial_mode in ("local", "api"):
            self.local.setChecked(initial_mode == "local")
            self.cloud.setChecked(initial_mode == "api")
            self.advance()

    def _choice_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(15)
        self.local = QRadioButton("Локальный ИИ\nБез ключей и оплаты за запросы")
        self.cloud = QRadioButton("Облачный API\nПодключить свой ключ")
        self.cloud.setChecked(self.cfg.get("ai_mode") in API_PROVIDERS)
        self.local.setChecked(not self.cloud.isChecked())
        layout.addWidget(self.local)
        layout.addWidget(label("Модель загружается один раз. Затем ответы генерируются на твоём ПК.", "muted"))
        layout.addWidget(self.cloud)
        layout.addWidget(label("OpenAI, Google Gemini, DeepSeek и другие сервисы. Нужны интернет и действующий ключ.", "muted"))
        layout.addStretch()
        self.pages.addWidget(page)

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(13)
        self.settings = QStackedWidget()
        local_page = QWidget()
        local = QVBoxLayout(local_page)
        local.setContentsMargins(0, 0, 0, 0)
        local.addWidget(label("Модель для твоего компьютера"))
        self.model_choice = QComboBox()
        for key, info in CATALOG.items():
            self.model_choice.addItem(info["label"], key)
        local.addWidget(self.model_choice)
        local.addWidget(label("Для начала подойдёт Qwen3 4B. Потребуется около 3 ГБ свободного места. Загрузка может занять несколько минут.", "muted"))
        local.addStretch()
        cloud_page = QWidget()
        cloud = QVBoxLayout(cloud_page)
        cloud.setContentsMargins(0, 0, 0, 0)
        cloud.setSpacing(10)
        cloud.addWidget(label("Сервис"))
        self.provider = QComboBox()
        for key, info in API_PROVIDERS.items():
            self.provider.addItem(info["label"], key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.cfg.get("ai_mode"))))
        cloud.addWidget(self.provider)
        cloud.addWidget(label("Ключ API"))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Вставь ключ выбранного сервиса")
        cloud.addWidget(self.key)
        show = QCheckBox("Показать ключ")
        show.toggled.connect(lambda checked: self.key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        cloud.addWidget(show)
        cloud.addWidget(label("Модель"))
        self.api_model = QLineEdit()
        cloud.addWidget(self.api_model)
        cloud.addWidget(label("Ключ сохраняется только в настройках на этом ПК. Использование API оплачивается по условиям выбранного сервиса.", "muted"))
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.provider_changed()
        self.settings.addWidget(local_page)
        self.settings.addWidget(cloud_page)
        layout.addWidget(self.settings, 1)
        self.status = label("", "muted")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.pages.addWidget(page)

    def _ready_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 18)
        layout.addWidget(label("✓   Можно знакомиться", "heading"))
        self.summary = label("", "subheading")
        layout.addWidget(self.summary)
        layout.addSpacing(22)
        layout.addWidget(label("Позови её: «Капри»\n\nПопробуй: «Капри, привет» или «Капри, походи».", "muted"))
        layout.addStretch()
        layout.addWidget(label("Режим ИИ можно поменять позже в настройках Капри.", "muted"))
        self.pages.addWidget(page)

    def provider_changed(self):
        provider = self.provider.currentData()
        self.key.setText(self.cfg.get(f"{provider}_api_key", ""))
        self.api_model.setText(self.cfg.get(f"{provider}_model") or API_PROVIDERS[provider]["model"])

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        self.error.clear()
        self.heading.setText(("Познакомимся?", "Настроим подключение", "Капри готова к встрече")[index])
        self.subtitle.setText(("Выбери, как Капри будет отвечать на твои вопросы.",
                               "Остался один небольшой шаг.", "Настройки сохранены. Дальше — самое интересное.")[index])
        self.back.setVisible(index == 1)
        self.next.setText(("Продолжить  →", "Скачать и подключить" if self.local.isChecked() else "Сохранить и продолжить", "Запустить Капри  →")[index])
        for number, step in enumerate(self.steps):
            step.setProperty("active", number == index)
            step.style().unpolish(step)
            step.style().polish(step)

    def previous(self):
        if not self.worker:
            self.change_page(0)

    def advance(self):
        index = self.pages.currentIndex()
        if index == 0:
            self.settings.setCurrentIndex(0 if self.local.isChecked() else 1)
            self.change_page(1)
        elif index == 2:
            self.accept()
        elif not self.local.isChecked():
            try:
                self.finish(api_settings(self.provider.currentData(), self.key.text(), self.api_model.text()))
            except (OSError, ValueError):
                self.error.setText("Укажи сервис, ключ API и модель. Проверь, что папка установки доступна для записи.")
        elif not self.worker:
            self.error.clear()
            self.status.setText("Подготавливаем модель и проверяем уже загруженные файлы…")
            self.progress.setRange(0, 0)
            self.progress.show()
            self.next.setEnabled(False)
            self.back.setEnabled(False)
            self.model_choice.setEnabled(False)
            self.worker = ModelDownload(self.base, self.model_choice.currentData(), self)
            self.worker.progress.connect(self.status.setText)
            self.worker.success.connect(lambda settings: setattr(self, "pending_settings", settings))
            self.worker.failed.connect(self.error.setText)
            self.worker.finished.connect(self.download_finished)
            self.worker.start()

    def download_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.next.setEnabled(True)
        self.back.setEnabled(True)
        self.model_choice.setEnabled(True)
        self.progress.hide()
        self.status.clear()
        if self.closing:
            super().reject()
        elif self.pending_settings:
            settings, self.pending_settings = self.pending_settings, None
            try:
                self.finish(settings)
            except (OSError, ValueError):
                self.error.setText("Модель готова, но настройки не удалось сохранить. Проверь права записи.")

    def finish(self, settings):
        save_setup(self.config_path, settings)
        self.summary.setText("Локальная модель установлена. Ключ API не нужен." if settings["ai_mode"] == "llamacpp"
                             else "Подключён " + API_PROVIDERS[settings["ai_mode"]]["label"] + ". Ключ будет использован при первом запросе.")
        self.change_page(2)

    def reject(self):
        if self.worker:
            self.closing = True
            self.status.setText("Отменяем загрузку…")
            self.worker.scope.cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
