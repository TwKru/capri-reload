"""Restart waits for the old process and preserves source/frozen entry points."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from capri.app import bootstrap, restart


class RestartTests(unittest.TestCase):
    def test_source_restart_uses_main_and_windowless_python(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root/"python.exe"
            (root/"pythonw.exe").touch()
            command = restart.restart_command(root,executable=executable,frozen=False,pid=1234)
            self.assertEqual(command[0],str(root/("pythonw.exe" if os.name == "nt" else "python.exe")))
            self.assertEqual(command[1:],[str(root/"main.py"),"--wait-for-pid","1234"])

    def test_frozen_restart_launches_same_executable(self):
        executable = Path("C:/Capri/Capri.exe")
        self.assertEqual(restart.restart_command(executable=executable,frozen=True,pid=1234),
                         [str(executable),"--wait-for-pid","1234"])

    def test_replacement_is_hidden_and_waits_for_this_pid(self):
        with patch.object(restart.subprocess,"Popen") as launch:
            restart.spawn_replacement(Path("C:/Capri"))
        self.assertEqual(launch.call_args.args[0][-2:],["--wait-for-pid",str(os.getpid())])
        self.assertEqual(launch.call_args.kwargs["creationflags"],0x08000000 if os.name == "nt" else 0)

    def test_wait_accepts_exited_process_and_rejects_live_timeout(self):
        process = Mock()
        with patch.object(restart.psutil,"Process",return_value=process):
            self.assertTrue(restart.wait_for_previous(1234))
            process.wait.assert_called_once_with(timeout=30)
            process.wait.side_effect = psutil.TimeoutExpired(30)
            self.assertFalse(restart.wait_for_previous(1234))
        with patch.object(restart.psutil,"Process",side_effect=psutil.NoSuchProcess(1234)):
            self.assertTrue(restart.wait_for_previous(1234))
        for pid in (0,-1,os.getpid()):
            with self.assertRaises(ValueError):
                restart.wait_for_previous(pid)

    def test_bootstrap_does_not_start_another_copy_if_old_one_is_still_running(self):
        with patch.object(bootstrap.sys,"argv",["main.py","--wait-for-pid","1234"]), \
             patch.object(restart,"wait_for_previous",return_value=False) as wait, \
             patch("capri.app.windows_application.run") as run:
            bootstrap.main()
            wait.assert_called_once_with("1234")
            run.assert_not_called()

    def test_bootstrap_continues_after_previous_copy_has_exited(self):
        with patch.object(bootstrap.sys,"argv",["main.py","--wait-for-pid","1234","--smoke-test","test-output"]), \
             patch.object(restart,"wait_for_previous",return_value=True) as wait, \
             patch("capri.app.diagnostics.smoke") as smoke:
            bootstrap.main()
            wait.assert_called_once_with("1234")
            smoke.assert_called_once_with("test-output")

    def test_restart_button_waits_for_outro_and_repeated_clicks_spawn_once(self):
        import copy

        from PySide6.QtWidgets import QApplication

        from capri.app import controller, windows_application
        from capri.desktop.avatar import Avatar
        from capri.ui.startup_animation import ScreenTransition

        app = QApplication.instance() or QApplication([])
        avatar = Avatar(str(Path(controller.BASE)/"assets"))
        transition = ScreenTransition()
        for callback in (avatar.close,avatar.overlay.close,avatar.timer.stop,transition.close,transition.timer.stop):
            self.addCleanup(callback)
        cfg = copy.deepcopy(controller.DEFAULTS)
        capri = Mock(cfg=cfg,voice_paused=False,last_request="")
        capri.actions.sites,capri.actions.apps = {},{}
        capri.listener = None
        runtime = Mock()

        def event_loop():
            click = runtime.restart_requested.connect.call_args.args[0]
            click()
            click()
            self.assertEqual(transition.mode,"shutdown")
            replacement.assert_not_called()
            transition.finished.emit("shutdown")
            app.quit.assert_called_once()
            replacement.assert_not_called()
            return 0

        with patch("capri.app.runtime_services.RuntimeServices",return_value=runtime), \
             patch.object(windows_application,"QApplication",return_value=app), \
             patch.object(windows_application,"Avatar",return_value=avatar), \
             patch.object(windows_application,"Capri",return_value=capri), \
             patch.object(windows_application,"ScreenTransition",return_value=transition), \
             patch.object(windows_application,"QSystemTrayIcon"), \
             patch.object(windows_application,"load_config",return_value=cfg), \
             patch.object(windows_application,"spawn_replacement") as replacement, \
             patch.object(app,"quit"),patch.object(app,"exec",side_effect=event_loop), \
             self.assertRaises(SystemExit):
            windows_application.main()
        replacement.assert_called_once_with(controller.BASE)
        capri.stop_listening.assert_called_once()
