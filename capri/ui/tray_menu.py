"""Все элементы управления Капри в одном красно-чёрном меню."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QWidget,
    QWidgetAction,
)

from capri.audio.voice_service import default_input_name, input_devices

MENU_STYLE = """
QMenu { background: #090609; border: 1px solid #ff224c; padding: 7px; }
QMenu, QMenu QWidget { color: #f4dce3; font-family: Consolas; font-size: 10pt; }
QMenu::item { padding: 8px 30px 8px 13px; }
QMenu::item:selected { background: #3b0b19; color: #ff486b; }
QMenu::item:disabled { color: #98616e; }
QMenu::separator { height: 1px; background: #582033; margin: 6px 9px; }
QMenu::indicator:checked { background: #ff224c; border: 1px solid #ff8097; }
QLabel { background: #090609; color: #f4dce3; }
QSlider::groove:horizontal { height: 5px; background: #36131f; }
QSlider::sub-page:horizontal { background: #bb173a; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #ff224c; border: 1px solid #ff8097; }
"""


def build_control_menu(capri, avatar, handlers, base):
    menu = QMenu()
    menu.setStyleSheet(MENU_STYLE)
    title = menu.addAction("CAPRI // CHIP CONTROL")
    title.setEnabled(False)
    menu.addSeparator()

    def action(parent, label, callback):
        item = parent.addAction(label)
        item.triggered.connect(lambda checked=False: callback())
        return item

    def command(parent, label, text):
        return action(parent, label, lambda: capri.text_command(text))

    if "mainframe" in handlers:
        action(menu, "MAINFRAME — управление Капри…", handlers["mainframe"])
    action(menu, "Позвать Капри", capri.call_from_click)
    action(menu, "Написать команду…", handlers["text"])
    edit = action(menu, "Изменить последний запрос…", handlers["edit"])
    microphone = action(menu, "Микрофон включён", lambda: capri.toggle_voice("idle" if capri.voice_paused else "listening"))
    microphone.setCheckable(True)
    action(menu, "Остановить речь и обработку", capri.stop_listening)
    action(menu, "Спрятать Капри", avatar.vanish)
    menu.addSeparator()

    settings = menu.addMenu("Настройки")
    for label, key in (("Нейросеть и API…", "ai"), ("Голос и чувствительность…", "sound"),
                       ("Как ко мне обращаться…", "profile"), ("Сайты, программы и ответы…", "entries")):
        action(settings, label, handlers[key])

    devices = settings.addMenu("Устройство микрофона")
    def fill_devices():
        devices.clear()
        choices = [(None, "По умолчанию: " + default_input_name())]
        try:
            choices += [(name, name) for name, _ in input_devices()]
        except Exception:
            pass
        for value, label in choices:
            item = devices.addAction(label)
            item.setCheckable(True)
            item.setChecked(value == (capri.cfg.get("mic_device") or None))
            item.triggered.connect(lambda checked=False, name=value: capri.set_mic(name))
    devices.aboutToShow.connect(fill_devices)

    volume = settings.addMenu("Громкость Капри")
    box = QWidget()
    box.setStyleSheet("background: #090609;")
    row = QHBoxLayout(box)
    row.setContentsMargins(12, 9, 12, 9)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setMinimumWidth(180)
    label = QLabel()
    label.setMinimumWidth(40)
    row.addWidget(slider)
    row.addWidget(label)
    slider.valueChanged.connect(lambda value: label.setText(f"{value}%"))
    slider.sliderReleased.connect(lambda: capri.set_voice_volume(slider.value()))
    slider.valueChanged.connect(lambda value: None if slider.isSliderDown() else capri.set_voice_volume(value))
    widget_action = QWidgetAction(volume)
    widget_action.setDefaultWidget(box)
    volume.addAction(widget_action)
    def sync_volume():
        slider.blockSignals(True)
        slider.setValue(int(capri.cfg.get("voice_volume", 100)))
        label.setText(f"{slider.value()}%")
        slider.blockSignals(False)
    volume.aboutToShow.connect(sync_volume)

    toggles = []
    for text, key, setter in (("Искать сведения в интернете", "search_when_unsure", capri.set_search_when_unsure),
                              ("Появляться самой", "chatter", capri.set_chatter),
                              ("Характер и настроение", "personality", capri.set_personality)):
        item = settings.addAction(text)
        item.setCheckable(True)
        item.toggled.connect(setter)
        toggles.append((item, key))
    action(settings, "Открыть config.json", lambda: os.startfile(str(Path(base) / "config.json")))

    memory = menu.addMenu("Разговор и память")
    action(memory, "Источники последнего ответа…", handlers["sources"])
    action(memory, "Открыть файл памяти…", lambda: os.startfile(str(Path(base) / "memory.json")))
    command(memory, "Что ты помнишь?", "что ты помнишь")
    command(memory, "Очистить память", "очисти память")

    gestures = menu.addMenu("Действия Капри")
    for label, text in (("Помахать", "помаши"), ("Полетать", "полетай"), ("Покрутиться", "покрутись"),
                        ("Потанцевать", "танцуй"), ("Подремать", "поспи"), ("Проснуться", "проснись")):
        command(gestures, label, text)
    position = gestures.addMenu("Переместиться")
    for label, text in (("В левый верхний угол", "встань в левый верхний угол"),
                        ("В правый верхний угол", "встань в правый верхний угол"),
                        ("В левый нижний угол", "встань в левый нижний угол"),
                        ("В правый нижний угол", "встань в правый нижний угол"),
                        ("В центр", "встань в центр")):
        command(position, label, text)

    media = menu.addMenu("Музыка и видео")
    for label, text in (("Включить музыку", "включи музыку"), ("Пауза", "пауза"), ("Продолжить", "продолжи музыку"),
                        ("Следующий трек", "следующий трек"), ("Предыдущий трек", "предыдущий трек"),
                        ("Что играет?", "что играет"), ("Перемешать", "перемешай песни"),
                        ("Повторять трек", "зацикли трек"), ("Выключить повтор", "выключи повтор")):
        command(media, label, text)
    computer = menu.addMenu("Компьютер")
    for label, text in (("Проверить ПК", "проверь компьютер"), ("Снимок экрана", "сделай скриншот"),
                        ("Заблокировать", "заблокируй компьютер"), ("Ночной режим", "ночь"),
                        ("Дневной режим", "день"), ("Выключить компьютер…", "выключи компьютер"),
                        ("Перезагрузить компьютер…", "перезагрузи компьютер")):
        command(computer, label, text)

    launch = menu.addMenu("Открыть сайт или программу")
    def fill_launch():
        launch.clear()
        for group, values in (("Сайты", capri.actions.sites), ("Программы", capri.actions.apps)):
            submenu = launch.addMenu(group)
            for name in sorted(values):
                command(submenu, name, "открой " + name)
            if not values:
                submenu.addAction("Пока пусто").setEnabled(False)
        action(launch, "Добавить сайт или программу…", handlers["entries"])
    launch.aboutToShow.connect(fill_launch)

    help_menu = menu.addMenu("Помощь и обновления")
    action(help_menu, "Все голосовые команды…", lambda: os.startfile(str(Path(base) / "docs" / "voice_commands.md")))
    command(help_menu, "Проверить обновления", "проверь обновления")
    command(help_menu, "Обновить Капри", "обновись")
    action(help_menu, "Капри на GitHub…", handlers["github"])
    menu.addSeparator()
    action(menu, "Извлечь чип и выйти", handlers["quit"])

    def sync():
        capri.reload_config_if_changed(speak=False)
        microphone.setChecked(not capri.voice_paused)
        microphone.setText("Микрофон на паузе — включить" if capri.voice_paused else "Микрофон включён — выключить")
        edit.setEnabled(bool(capri.last_request))
        for item, key in toggles:
            item.blockSignals(True)
            item.setChecked(bool(capri.cfg.get(key, True)))
            item.blockSignals(False)
    menu.aboutToShow.connect(sync)
    return menu
