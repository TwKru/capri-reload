"""Сборка Windows-интерфейса: QApplication, аватар, меню и жизненный цикл."""
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from capri.app.controller import BASE, Capri, fatal
from capri.app.restart import spawn_replacement
from capri.automation.command_dispatcher import CAPRI_URL
from capri.config.settings import apply_user, load_config
from capri.desktop.avatar import Avatar
from capri.ui.garbage_collection import GuiGarbageCollector
from capri.ui.startup_animation import ScreenTransition, chip_icon
from capri.ui.theme import CyberInputDialog as QInputDialog
from capri.ui.theme import CyberMessageBox as QMessageBox
from capri.ui.theme import apply_theme
from capri.ui.tray_menu import build_control_menu

log = logging.getLogger("capri")

def run():
    """Сохраняет видимую диагностику ошибок при запуске через pythonw/EXE."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        log.exception("Капри упала при запуске")
        fatal(f"Что-то сломалось при запуске: {error}\n\nПодробности — в файле capri.log в папке Капри.")


def tray_icon():
    return chip_icon()


def main():
    app = QApplication(sys.argv)
    collector = GuiGarbageCollector(app)
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    config_missing = not (Path(BASE) / "config.json").exists()
    cfg = load_config()
    if config_missing or cfg.get("setup_pending") or "--setup" in sys.argv:
        from capri.config.settings import _edit_config
        from capri.ui.setup_wizard import SetupWizard
        if config_missing:
            _edit_config(lambda data: data.update(setup_pending=True))
        initial_mode = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--setup-mode=")), None)
        wizard = SetupWizard(cfg, initial_mode=initial_mode)
        if not wizard.exec():
            return
        cfg = load_config()

    avatar = Avatar(os.path.join(BASE, "assets"))
    avatar.hide_after = float(cfg["hide_after_seconds"])
    apply_user(cfg)
    capri = Capri(cfg)
    avatar.speech_active = lambda: bool(capri.speaker.playing)
    capri.enable_memory(os.path.join(BASE, "memory.json"))
    from capri.app.runtime_services import RuntimeServices
    extensions = capri.extensions = RuntimeServices(capri, avatar, BASE)
    capri.mood_changed.connect(avatar.set_mood)
    maintenance_timer = QTimer(app)
    maintenance_timer.setInterval(1000)
    maintenance_timer.timeout.connect(capri.expire_answer)
    maintenance_timer.timeout.connect(capri.sync_personality)
    maintenance_timer.start()
    capri.summon.connect(avatar.summon)
    capri.vanish.connect(avatar.vanish)
    capri.mode.connect(avatar.set_mode)
    capri.voice_paused_changed.connect(avatar.set_voice_paused)
    capri.subtitle.connect(avatar.set_subtitle)
    capri.anim.connect(avatar.play_anim)
    capri.roam.connect(avatar.start_roam)
    capri.stop_motion.connect(avatar.stop_motion)
    capri.hop.connect(avatar.start_hopping)
    capri.move_to.connect(avatar.move_to_named)
    avatar.clicked.connect(capri.call_from_click)
    avatar.petted.connect(lambda: capri.jobs.put(("pet",)))

    def ask_text():
        text, ok = QInputDialog.getText(None, "Капри", "Команда или вопрос:")
        if ok and text.strip():
            capri.text_command(text.strip())

    windows = {}  # открытые окна держим, пока открыты (иначе их соберёт сборщик мусора); одно окно каждого вида

    def show_window(kind, make):
        old = windows.get(kind)
        if old is not None and old.isVisible():
            old.close()
        dlg = windows[kind] = make()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_entries():
        from capri.ui.dialogs.app_shortcuts import EntriesDialog
        capri.reload_config_if_changed(speak=False)
        show_window("entries", lambda: EntriesDialog(capri.actions))

    def open_sound():
        from capri.ui.dialogs.audio_settings import SoundDialog
        show_window("sound", lambda: SoundDialog(capri))

    def open_profile():
        from capri.ui.dialogs.user_profile import ProfileDialog
        show_window("profile", lambda: ProfileDialog(capri))

    def open_ai():
        from capri.ui.dialogs.ai_settings import AIDialog
        show_window("ai", lambda: AIDialog(capri))

    def show_sources():
        sources = capri.last_web_sources
        text = "\n\n".join(f"{item['title']}\n{item['url']}" for item in sources) if sources else "Для последнего веб-поиска источников пока нет."
        dialog = QMessageBox()
        dialog.setWindowTitle("Источники ответа Капри")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dialog.setText(text)
        show_window("sources", lambda: dialog)

    transition = ScreenTransition()
    lifecycle = {"shutting_down": False, "started": False, "restart": False}

    def quit_with_animation():
        if lifecycle["shutting_down"]:
            return
        lifecycle["shutting_down"] = True
        maintenance_timer.stop()
        transition.play("shutdown", avatar)
        capri.voice_paused = True
        if capri.listener:
            capri.listener.muted.set()
        capri.stop_listening()
        capri.summon.disconnect(avatar.summon)
        capri.roam.disconnect(avatar.start_roam)
        avatar.stop_motion()
        avatar.timer.stop()
        avatar.hide()
        menu.close()
        tray.setContextMenu(None)
        for window in windows.values():
            window.close()

    def restart_with_animation():
        if lifecycle["shutting_down"]:
            return
        lifecycle["restart"] = True
        quit_with_animation()

    extensions.restart_requested.connect(restart_with_animation)
    menu = build_control_menu(capri, avatar, {
        "mainframe": extensions.show,
        "text": ask_text, "edit": lambda: capri.edit_request(avatar), "entries": open_entries,
        "profile": open_profile, "sound": open_sound, "ai": open_ai, "sources": show_sources,
        "github": lambda: capri.actions.web(CAPRI_URL), "quit": quit_with_animation,
        "restart": restart_with_animation,
    }, BASE)
    tray = QSystemTrayIcon(tray_icon())
    tray.setToolTip("Капри — чип подключён · ПКМ: меню")
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: capri.call_from_click()
                           if reason == QSystemTrayIcon.ActivationReason.Trigger and not lifecycle["shutting_down"] else None)
    tray.show()

    def show_menu():
        if lifecycle["shutting_down"]:
            return
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QCursor
        anchor = QPoint(avatar.x() + avatar.width() + 8, avatar.y() + 370) if avatar.isVisible() else QCursor.pos()
        menu.popup(anchor)

    def transition_finished(kind):
        if kind == "startup" and not lifecycle["shutting_down"] and not lifecycle["started"]:
            lifecycle["started"] = True
            capri.start()
        elif kind == "shutdown":
            tray.hide()
            app.quit()

    extensions.install_hotkeys(ask_text, app)
    app.aboutToQuit.connect(extensions.close)
    capri.menu_requested.connect(show_menu)
    capri.quit_app.connect(quit_with_animation)
    transition.finished.connect(transition_finished)
    transition.revealed.connect(avatar.summon)
    if cfg.get("first_start_mainframe",False):
        extensions.show()
        extensions.save({"first_start_mainframe":False})
    transition.play("startup")
    try:
        result = app.exec()
    finally:
        collector.close()
    if lifecycle["restart"]:
        # aboutToQuit has already stopped speech, native workers and active tasks.
        # The child waits for this PID before opening its microphone or interface.
        spawn_replacement(BASE)
    sys.exit(result)
