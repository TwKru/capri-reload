"""Красно-чёрная панель: рабочий стол, память, файлы, расписание и локальные модели."""
import json
import threading
import time

from PySide6.QtCore import QDateTime, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from capri.ai.persona.personality_file import LANGUAGES
from capri.desktop.window_companion import HOTKEYS
from capri.ui.theme import CyberDialog, CyberMessageBox

STYLE = """
QWidget { background:#090609; color:#f4dce3; font-family:Consolas; font-size:10pt; }
QLabel#capriWindowTitle { color:#ff365f; }
QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox,QDoubleSpinBox,QDateTimeEdit {
 background:#170a10; border:1px solid #6d2035; padding:6px; selection-background-color:#9b1637; }
QPushButton { background:#2a0b16; border:1px solid #f32654; padding:8px 12px; }
QPushButton:hover { background:#63102b; } QPushButton:disabled { color:#76505a; border-color:#48303a; }
QTabBar::tab { padding:10px; background:#170a10; } QTabBar::tab:selected { color:#ff466c; border-bottom:2px solid #ff224c; }
QCheckBox { spacing:8px; } QCheckBox::indicator:checked { background:#ff224c; border:1px solid #ff8097; }
QLabel#heading { font-size:18pt; color:#ff365f; } QScrollArea { border:0; }
"""
STATUS = {"scheduled":"По расписанию","queued":"В очереди","running":"Выполняется","paused":"Пауза",
          "failed":"Ошибка","awaiting_confirmation":"Нужно разрешение","done":"Готово","cancelled":"Отменено"}


class Mainframe(CyberDialog):
    downloaded = Signal(object)
    progress = Signal(str)

    def __init__(self, runtime):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.runtime, self.capri = runtime, runtime.capri
        self.frame_background, self.frame_accent = "#090609", "#ff224c"
        self.setWindowTitle("Капри — MAINFRAME")
        self.setStyleSheet(STYLE)
        self.resize(930, 740)
        self.setMinimumSize(560, 400)
        screen = QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(min(930,max(560,area.width()-32)),min(740,max(400,area.height()-32)))
        self.title_bar.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        heading = QLabel("CAPRI // MAINFRAME")
        heading.setObjectName("heading")
        heading.setStyleSheet("color:#ff365f; font-size:18pt;")
        layout.addWidget(heading)
        self.status = QLabel("Локальные настройки · экран по запросу · Escape останавливает агента")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.button("Перезапустить Капри",self.runtime.request_restart))
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(STYLE)
        layout.addWidget(self.tabs)
        self.desktop_tab()
        self.tasks_tab()
        self.files_tab()
        self.persona_tab()
        self.models_tab()
        self.system_tab()
        self.downloaded.connect(self.download_complete)
        self.progress.connect(self.status.setText)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh_tasks)
        self.timer.start()
        self.refresh_tasks()

    def page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setStyleSheet(STYLE)
        form = QFormLayout(page)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setContentsMargins(14,14,14,14)
        form.setSpacing(12)
        scroll.setWidget(page)
        self.tabs.addTab(scroll,title)
        return form

    def button(self, text, callback):
        button = QPushButton(text)
        button.clicked.connect(lambda checked=False:self.guard(callback))
        return button

    def guard(self, callback):
        try:
            callback()
        except (OSError, ValueError, UnicodeError) as error:
            CyberMessageBox.warning(self,"Капри",str(error))

    def check(self, text, key, default=False):
        check = QCheckBox(text)
        check.setChecked(self.capri.cfg.get(key,default))
        check.toggled.connect(lambda value:self.guard(lambda:self.runtime.save({key:value})))
        return check

    def desktop_tab(self):
        form = self.page("Рабочий стол")
        form.addRow(self.check("Садиться на окна и значки при отпускании", "desktop_perching",True))
        form.addRow(self.check("Гулять между открытыми окнами", "window_wander",False))
        hint = QLabel("Перетащи Капри к верхнему краю окна или значка. Ctrl при отпускании — висеть; Shift — точное положение. Клик — позвать, поглаживание головы — реакция.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(.5,1.6)
        self.scale.setSingleStep(.1)
        self.scale.setValue(self.capri.cfg.get("avatar_scale",1.))
        self.scale.valueChanged.connect(lambda value:self.guard(lambda:self.runtime.save({"avatar_scale":value})))
        form.addRow("Размер Капри:",self.scale)
        for label, callback in (("Сесть на следующее окно",self.runtime.life.hop_window),
            ("Кататься на курсоре",self.runtime.life.ride_cursor),("Отцепиться",self.runtime.life.detach),
            ("Гулять",self.runtime.avatar.start_roam),("Спать",lambda:self.runtime.avatar.play_anim("desktop_sleep")),
            ("Танцевать",lambda:self.capri.text_command("танцуй"))):
            form.addRow(self.button(label,callback))
        form.addRow(self.check("Танцевать под воспроизводимую музыку", "music_dance",False))
        form.addRow(self.check("Фоновый комментарий экрана (передача снимков модели)","screen_watch",False))
        self.interval = QSpinBox()
        self.interval.setRange(60,3600)
        self.interval.setSuffix(" секунд")
        self.interval.setValue(self.capri.cfg.get("screen_watch_seconds",300))
        self.interval.valueChanged.connect(lambda value:self.guard(lambda:self.runtime.save({"screen_watch_seconds":value})))
        form.addRow("Интервал наблюдения:",self.interval)
        form.addRow(self.button("Посмотреть экран один раз",lambda:self.capri.jobs.put(("see","Что сейчас на моём экране?"))))

    def tasks_tab(self):
        form = self.page("Задания")
        self.task_engine = QComboBox()
        self.task_engine.addItem("Обычный агент — текущая нейросеть", "default")
        self.task_engine.addItem("Computer Use — OpenAI, управление по снимкам экрана", "computer_use")
        form.addRow("Исполнитель:",self.task_engine)
        self.computer_key = QLineEdit(self.capri.cfg.get("openai_api_key",""))
        self.computer_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.computer_key.setPlaceholderText("Ключ OpenAI или OPENAI_API_KEY")
        self.computer_model = QLineEdit(self.capri.cfg.get("computer_use_model","gpt-6.1-sol"))
        form.addRow("Ключ OpenAI для Computer Use:",self.computer_key)
        form.addRow("Модель Computer Use:",self.computer_model)
        form.addRow(self.button("Сохранить настройки Computer Use",self.save_computer_settings))
        hint = QLabel("Computer Use работает на главном мониторе и передаёт его снимки в OpenAI API во время задания. "
                      "Команда: «Капри, управляй компьютером: открой Блокнот и введи привет». Escape или «Капри, стоп» останавливает выполнение.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText("Опиши результат. Например: прочитай выбранный файл и исправь опечатки.")
        self.request.setMaximumHeight(105)
        form.addRow("Новая задача:",self.request)
        self.when = QDateTimeEdit(QDateTime.currentDateTime())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd.MM.yyyy HH:mm")
        form.addRow("Начать:",self.when)
        self.repeat = QComboBox()
        for name,seconds in (("Один раз",0),("Каждый час",3600),("Каждый день",86400),("Каждую неделю",604800)):
            self.repeat.addItem(name,seconds)
        form.addRow("Повтор:",self.repeat)
        self.steps = QSpinBox(); self.steps.setRange(1,500); self.steps.setValue(60)
        self.minutes = QSpinBox(); self.minutes.setRange(1,720); self.minutes.setValue(60)
        limits = QWidget(); row = QHBoxLayout(limits); row.setContentsMargins(0,0,0,0)
        row.addWidget(QLabel("Шагов")); row.addWidget(self.steps); row.addWidget(QLabel("Минут")); row.addWidget(self.minutes)
        form.addRow("Лимиты:",limits)
        form.addRow(self.check("Разрешить снимки и клики агента для заданий", "agent_screen",False))
        form.addRow(self.check("Сначала показывать план (+1 запрос на задание)", "plan_tasks",False))
        form.addRow(self.button("Добавить задание",self.add_task))
        self.tasks = QListWidget()
        self.tasks.setMinimumHeight(130)
        self.tasks.currentRowChanged.connect(lambda _:self.refresh_log())
        form.addRow(self.tasks)
        buttons = QWidget(); row = QHBoxLayout(buttons); row.setContentsMargins(0,0,0,0)
        row.addWidget(self.button("Пауза / Escape",self.pause_task))
        row.addWidget(self.button("Продолжить",self.resume_task))
        row.addWidget(self.button("Разрешить показанный шаг",self.approve_task))
        form.addRow(buttons)
        form.addRow(self.button("Отменить выбранное задание и его повторы",self.cancel_task))
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(120)
        form.addRow("Журнал:",self.log)
        self.task_signature = None

    def selected_task(self):
        item = self.tasks.currentItem()
        if item is None:
            raise ValueError("Выбери задание")
        return item.data(Qt.ItemDataRole.UserRole)

    def add_task(self):
        self.runtime.store.create(self.request.toPlainText(),due=self.when.dateTime().toSecsSinceEpoch(),
            repeat=self.repeat.currentData(),max_steps=self.steps.value(),seconds=self.minutes.value()*60,
            engine=self.task_engine.currentData())
        self.request.clear()
        self.refresh_tasks()

    def save_computer_settings(self):
        model = self.computer_model.text().strip()
        if not model:
            raise ValueError("Укажи модель с поддержкой Computer Use")
        self.runtime.save({"openai_api_key":self.computer_key.text().strip(),"computer_use_model":model})
        self.status.setText("Настройки Computer Use сохранены")

    def resume_task(self):
        ident = self.selected_task()
        if self.runtime.store.get(ident)["status"] == "awaiting_confirmation":
            raise ValueError("Прочитай заблокированный шаг в журнале и используй отдельную кнопку разрешения.")
        self.runtime.store.resume(ident)
        self.refresh_tasks()

    def pause_task(self):
        ident = self.selected_task()
        row = self.runtime.store.get(ident)
        if row["status"] in ("running","queued"):
            self.runtime.stop()
        elif row["status"] == "scheduled":
            self.runtime.store.update(ident,status="paused")
        self.refresh_tasks()

    def cancel_task(self):
        ident = self.selected_task()
        row = self.runtime.store.get(ident)
        if row["status"] in ("running","queued"):
            self.runtime.stop()
        if row["status"] != "done":
            self.runtime.store.update(ident,status="cancelled",result="Задание и его повторы отменены.")
        self.refresh_tasks()

    def approve_task(self):
        ident = self.selected_task()
        runner = self.runtime.runner_for(ident)
        pending = runner.pending.get(ident)
        if not pending or self.runtime.store.get(ident)["status"] != "awaiting_confirmation":
            raise ValueError("Нет заблокированного шага для разрешения")
        preview = json.dumps(pending[0],ensure_ascii=False,indent=2)
        if CyberMessageBox.question(self,"Разрешить один шаг?",preview,
            CyberMessageBox.StandardButton.Yes | CyberMessageBox.StandardButton.No) == CyberMessageBox.StandardButton.Yes:
            runner.approve(ident)
        self.refresh_tasks()

    def refresh_tasks(self):
        rows = self.runtime.store.list()
        signature = [(r["id"],r["status"],r["progress"],r["result"],r["due"]) for r in rows]
        if signature == self.task_signature:
            return
        self.task_signature = signature
        current = self.tasks.currentItem()
        ident = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.tasks.blockSignals(True)
        self.tasks.clear()
        for row in rows:
            self.tasks.addItem(f"#{row['id']} · {STATUS.get(row['status'],row['status'])} · {row['progress']}/{row['max_steps']} · {row['request'][:95]}")
            item = self.tasks.item(self.tasks.count()-1)
            item.setData(Qt.ItemDataRole.UserRole,row["id"])
            if row["id"] == ident:
                self.tasks.setCurrentItem(item)
        self.tasks.blockSignals(False)
        if self.tasks.currentRow() < 0 and rows:
            self.tasks.setCurrentRow(0)
        self.refresh_log()

    def refresh_log(self):
        if not hasattr(self,"log") or self.tasks.currentItem() is None:
            return
        ident = self.selected_task()
        row = self.runtime.store.get(ident)
        lines = [time.strftime("%d.%m %H:%M:%S",time.localtime(item["at"]))+"  "+item["text"] for item in self.runtime.store.log(ident)]
        runner = self.runtime.runner_for(ident)
        if ident in runner.pending:
            lines.append(json.dumps(runner.pending[ident][0],ensure_ascii=False,indent=2))
        self.log.setPlainText("\n".join(lines)+"\n"+row["result"])

    def files_tab(self):
        form = self.page("Файлы")
        form.addRow(QLabel("ИИ получает доступ только к выбранным текстовым файлам до 1 МБ."))
        self.file_list = QListWidget()
        self.file_list.addItems(list(self.runtime.files.grants))
        self.file_list.currentTextChanged.connect(lambda name:self.guard(lambda:self.load_file(name)))
        form.addRow(self.file_list)
        rowbox = QWidget(); row = QHBoxLayout(rowbox); row.setContentsMargins(0,0,0,0)
        row.addWidget(self.button("Выбрать файлы…",self.select_files))
        row.addWidget(self.button("Убрать доступ",self.revoke_file))
        form.addRow(rowbox)
        self.editor = QPlainTextEdit(); self.editor.setMinimumHeight(280)
        form.addRow(self.editor)
        form.addRow(self.button("Сохранить правки (с резервной копией)",lambda:self.runtime.files.write(self.file_list.currentItem().text(),self.editor.toPlainText()) if self.file_list.currentItem() else None))
        form.addRow(self.button("Вернуть резервную копию",self.restore_file))

    def select_files(self):
        names,_ = QFileDialog.getOpenFileNames(self,"Разрешённые файлы","","Текстовые файлы (*);;Markdown (*.md)",options=QFileDialog.Option.DontUseNativeDialog)
        if names:
            from capri.storage.file_workspace import FileWorkspace
            self.runtime.stop()
            paths = list(dict.fromkeys([*self.runtime.files.grants,*names]))
            self.runtime.save({"selected_files":paths})
            self.runtime.files.grants = FileWorkspace(paths).grants
            self.file_list.clear(); self.file_list.addItems(paths)

    def revoke_file(self):
        item = self.file_list.currentItem()
        if item:
            self.runtime.stop()
            self.runtime.files.grants.pop(item.text(),None)
            self.runtime.files.observed.pop(item.text(),None)
            self.runtime.save({"selected_files":list(self.runtime.files.grants)})
            self.file_list.takeItem(self.file_list.row(item))
            self.editor.clear()

    def load_file(self, name):
        if name:
            self.editor.setPlainText(self.runtime.files.read(name))

    def restore_file(self):
        if self.file_list.currentItem():
            name = self.file_list.currentItem().text()
            self.runtime.files.restore(name)
            self.load_file(name)

    def persona_tab(self):
        form = self.page("Личность и память")
        self.language = QComboBox()
        for code,name in LANGUAGES.items():
            self.language.addItem(name,code)
        self.language.setCurrentIndex(max(0,self.language.findData(self.capri.cfg.get("response_language","ru"))))
        self.language.currentIndexChanged.connect(lambda _:self.guard(lambda:self.runtime.save({"response_language":self.language.currentData()})))
        form.addRow("Язык ответов:",self.language)
        self.persona = QPlainTextEdit((self.runtime.base/"personality.md").read_text(encoding="utf-8-sig"))
        self.persona.setMinimumHeight(210)
        form.addRow("personality.md:",self.persona)
        form.addRow(self.button("Применить характер",lambda:(self.runtime.base/"personality.md").write_text(self.persona.toPlainText(),encoding="utf-8")))
        form.addRow(self.button("Восстановить исходный характер",self.reset_persona))
        self.notes = QPlainTextEdit((self.runtime.base/"me.md").read_text(encoding="utf-8-sig"))
        self.notes.setMinimumHeight(130)
        form.addRow("me.md — заметки обо мне:",self.notes)
        form.addRow(self.button("Сохранить заметки",lambda:(self.runtime.base/"me.md").write_text(self.notes.toPlainText(),encoding="utf-8")))
        form.addRow(QLabel("История хранится до 7 дней. Личные файлы исключены из публикации и защищены от обновлений."))

    def reset_persona(self):
        from capri.ai.persona.personality_file import reset
        reset(self.runtime.base/"personality.md")
        self.persona.setPlainText((self.runtime.base/"personality.md").read_text(encoding="utf-8"))

    def models_tab(self):
        from capri.ai.providers.llama_cpp import CATALOG
        form = self.page("Локальные модели")
        form.addRow(self.button("Выбрать API / Ollama / GGUF…",self.open_ai))
        self.catalog = QComboBox()
        for key, info in CATALOG.items():
            self.catalog.addItem(info["label"],key)
        form.addRow("Готовая модель:",self.catalog)
        self.eyes = QCheckBox("Также скачать зрение Gemma (~560 МБ)")
        form.addRow(self.eyes)
        self.download_button = self.button("Скачать llama.cpp и выбранную модель",self.download_model)
        form.addRow(self.download_button)
        self.model_paths = {}
        for label,key in (("llama-server:","llama_executable"),("GGUF:","llama_model"),("mmproj (необязательно):","llama_mmproj")):
            field = QLineEdit(self.capri.cfg.get(key,""))
            self.model_paths[key] = field
            box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0,0,0,0)
            row.addWidget(field)
            row.addWidget(self.button("…",lambda f=field:self.pick_model(f)))
            form.addRow(label,box)
        form.addRow(self.button("Применить локальные пути",lambda:self.runtime.save({key:field.text().strip() for key,field in self.model_paths.items()})))
        hint = QLabel("Загрузка начинается только по кнопке. Файлы проверяются по закреплённому SHA256. GGUF запускается при первом запросе; сервер слушает только 127.0.0.1. В API-режиме локальная модель не запускается.")
        hint.setWordWrap(True); form.addRow(hint)

    def open_ai(self):
        from capri.ui.dialogs.ai_settings import AIDialog
        AIDialog(self.capri).exec()

    def pick_model(self, field):
        name,_ = QFileDialog.getOpenFileName(self,"Выбрать файл",str(self.runtime.base/"models"),"Все файлы (*)",options=QFileDialog.Option.DontUseNativeDialog)
        if name:
            field.setText(name)

    def download_model(self):
        name, eyes = self.catalog.currentData(), self.eyes.isChecked()
        self.download_button.setEnabled(False)
        def work():
            from capri.ai.providers.llama_cpp import install
            try:
                self.downloaded.emit(install(self.runtime.base,name,eyes,self.progress.emit))
            except Exception as error:  # noqa: BLE001 -- граница фонового задания: ошибка передаётся в интерфейс
                self.downloaded.emit(str(error))
        threading.Thread(target=work,daemon=True).start()

    def download_complete(self, result):
        self.download_button.setEnabled(True)
        if isinstance(result,str):
            self.status.setText(result)
            return
        self.guard(lambda:self.runtime.save(result))
        for key,value in result.items():
            self.model_paths[key].setText(value)
        self.status.setText("Модель загружена и проверена. Включи режим GGUF в выборе нейросети.")

    def system_tab(self):
        form = self.page("Клавиши и запуск")
        self.keys = {}
        titles = {"talk":"Позвать","mute":"Микрофон","type":"Ввести запрос","hide":"Спрятать","detach":"Отцепиться"}
        for key,default in HOTKEYS.items():
            field = QLineEdit(self.capri.cfg.get("hotkeys",{}).get(key,default))
            self.keys[key] = field
            form.addRow(titles[key],field)
        form.addRow(self.button("Применить горячие клавиши",self.save_keys))
        form.addRow(QLabel("Escape занят только во время задания агента. Занятые сочетания отображаются ниже."))
        self.hotkey_status = QLabel("\n".join(self.runtime.hotkeys.errors) if self.runtime.hotkeys else "")
        self.hotkey_status.setWordWrap(True); form.addRow(self.hotkey_status)
        self.autostart = QCheckBox("Запускать Капри при входе в Windows")
        from capri.platform.startup import enabled
        self.autostart.setChecked(enabled())
        self.autostart.toggled.connect(lambda value:self.guard(lambda:self.set_autostart(value)))
        form.addRow(self.autostart)
        self.recognizer = QComboBox()
        for label, value in (("Vosk — русский, офлайн","vosk"),("Parakeet / Sherpa-ONNX — офлайн","parakeet"),("Windows Speech — системный микрофон","windows")):
            self.recognizer.addItem(label,value)
        self.recognizer.setCurrentIndex(max(0,self.recognizer.findData(self.capri.cfg.get("recognizer_backend","vosk"))))
        form.addRow("Распознавание речи:",self.recognizer)
        self.parakeet_path = QLineEdit(self.capri.cfg.get("parakeet_path",""))
        form.addRow("Папка ONNX Parakeet:",self.parakeet_path)
        form.addRow(self.button("Сохранить распознавание (после перезапуска)",lambda:self.runtime.save({"recognizer_backend":self.recognizer.currentData(),"parakeet_path":self.parakeet_path.text().strip()})))
        help = QLabel("Для Parakeet нужны sherpa-onnx и папка с encoder/decoder/joiner.onnx, tokens.txt. Выбирай модель с нужным языком. При ошибке Parakeet используется Vosk. Озвучка остаётся прежней.")
        help.setWordWrap(True); form.addRow(help)
        form.addRow(self.button("Проверить обновления",lambda:self.capri.text_command("проверь обновления")))

    def save_keys(self):
        from capri.desktop.window_companion import GlobalHotkeys
        values = {key:field.text().strip() for key,field in self.keys.items()}
        for value in values.values():
            GlobalHotkeys.parse(value)
        if len({value.upper() for value in values.values()}) != len(values):
            raise ValueError("Сочетания должны отличаться")
        self.runtime.save({"hotkeys":values})
        self.hotkey_status.setText("\n".join(self.runtime.hotkeys.errors) if self.runtime.hotkeys else "")

    def set_autostart(self, value):
        from capri.platform.startup import set_enabled
        set_enabled(value,self.runtime.base)
