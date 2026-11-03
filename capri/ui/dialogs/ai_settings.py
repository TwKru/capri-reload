"""Выбор локальной нейросети, OpenAI или Google AI Studio."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from capri.ai.providers.cloud_providers import PROVIDERS
from capri.ai.providers.gemini_provider import DEFAULT_GEMINI_MODEL
from capri.ui.theme import STYLE
from capri.ui.theme import CyberDialog as QDialog
from capri.ui.theme import CyberMessageBox as QMessageBox


class AIDialog(QDialog):
    def __init__(self, capri):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.capri = capri
        self.setWindowTitle("Капри — нейросеть и API")
        self.setStyleSheet(STYLE)
        form = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("Локальная модель (Ollama)", "local")
        self.mode.addItem("OpenAI API — без локальных моделей", "openai")
        self.mode.addItem("Google AI Studio / Gemini — API", "gemini")
        self.mode.addItem("Локальная GGUF (llama.cpp)", "llamacpp")
        for name, info in PROVIDERS.items():
            self.mode.addItem(info["label"] + " — API", name)
        self.mode.setCurrentIndex(max(0, self.mode.findData(capri.cfg.get("ai_mode", "local"))))
        form.addRow("Режим:", self.mode)
        self.key = QLineEdit(capri.cfg.get("openai_api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Ключ API или переменная OPENAI_API_KEY")
        self.key_label = QLabel("Ключ OpenAI:")
        form.addRow(self.key_label, self.key)
        self.model = QLineEdit(capri.cfg.get("openai_model") or "gpt-6-luna")
        self.model_label = QLabel("Модель OpenAI:")
        form.addRow(self.model_label, self.model)
        self.gemini_key = QLineEdit(capri.cfg.get("gemini_api_key", ""))
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key.setPlaceholderText("Ключ AI Studio или GEMINI_API_KEY / GOOGLE_API_KEY")
        self.gemini_key_label = QLabel("Ключ Google:")
        form.addRow(self.gemini_key_label, self.gemini_key)
        self.gemini_model = QLineEdit(capri.cfg.get("gemini_model") or DEFAULT_GEMINI_MODEL)
        self.gemini_model_label = QLabel("Модель Gemini:")
        form.addRow(self.gemini_model_label, self.gemini_model)
        self.extra_fields = {}
        for name, info in PROVIDERS.items():
            key = QLineEdit(capri.cfg.get(name + "_api_key", ""))
            key.setEchoMode(QLineEdit.EchoMode.Password)
            model = QLineEdit(capri.cfg.get(name + "_model") or info["model"])
            key_label, model_label = QLabel("Ключ " + info["label"] + ":"), QLabel("Модель:")
            form.addRow(key_label, key)
            form.addRow(model_label, model)
            self.extra_fields[name] = (key_label, key, model_label, model)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addRow(self.hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.update_fields()
        self.resize(540, 0)

    def update_fields(self):
        mode = self.mode.currentData()
        for name, widgets in self.extra_fields.items():
            for widget in widgets:
                widget.setVisible(mode == name)
        for widget in (self.key_label, self.key, self.model_label, self.model):
            widget.setVisible(mode in ("openai", "local"))
            widget.setEnabled(mode == "openai")
        for widget in (self.gemini_key_label, self.gemini_key, self.gemini_model_label, self.gemini_model):
            widget.setVisible(mode == "gemini")
        if mode in ("local", "llamacpp"):
            self.hint.setText("Локальный режим: Ollama или GGUF. Загрузка GGUF доступна в MAINFRAME. Ключи API не требуются.\n"
                              "Настройки провайдеров сохраняются отдельно.")
        else:
            provider = "Google AI Studio / Gemini" if mode == "gemini" else PROVIDERS.get(mode,{}).get("label","OpenAI")
            economy = self.capri.cfg.get(f"{mode}_min_tokens", True)
            self.hint.setText(f"Запросы отправляются в {provider}; нужен интернет.\n"
                              "Ollama и локальные языковые модели не запускаются.\n" +
                              ("Экономия токенов включена; память сохраняется в файле.\n" if economy else "") +
                              "Ключ хранится в config.json. Ключ другого API не меняется.\n"
                              "Переключение применяется сразу.")

    def save(self):
        try:
            mode = self.mode.currentData()
            key, model = ((self.gemini_key, self.gemini_model) if mode == "gemini" else (self.key, self.model))
            if mode in self.extra_fields:
                _, key, _, model = self.extra_fields[mode]
            self.capri.set_ai_settings(mode, key.text(), model.text())
        except (OSError, ValueError):
            QMessageBox.warning(self, "Капри", "Не удалось сохранить настройки. Проверь config.json и права записи.")
            return
        self.accept()
