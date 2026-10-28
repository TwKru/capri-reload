"""Обновления: свой репозиторий, личные файлы, обход путей и откат."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import updater
from actions import Actions


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.base, self.staged = self.root / "app", self.root / "staged"
        self.base.mkdir()
        self.staged.mkdir()
        (self.base / "main.py").write_text("old = True\n")
        (self.staged / "main.py").write_text("new = True\n")
        self.sha = "a" * 40

    def test_version_and_download_use_only_user_repository(self):
        data = json.dumps({"object": {"sha": self.sha}}).encode()
        with patch("updater.urllib.request.urlopen", return_value=io.BytesIO(data)) as request:
            self.assertEqual(updater.latest_version(), self.sha)
        self.assertEqual(request.call_args.args[0].full_url,
                         "https://api.github.com/repos/TwKru/capri-reload/git/ref/heads/main")
        with patch("updater.urllib.request.urlopen", return_value=io.BytesIO(b"archive")) as request:
            updater.download(self.sha, self.root / "download.zip")
        self.assertEqual(request.call_args.args[0].full_url,
                         "https://codeload.github.com/TwKru/capri-reload/zip/" + self.sha)

    def test_install_preserves_personal_files_git_and_unknown_files(self):
        for name in ("config.json", "capri.log", "my-notes.txt"):
            (self.base / name).write_text("personal")
        (self.staged / "config.json").write_text("must not replace")
        (self.base / ".git").mkdir()
        (self.base / ".git" / "config").write_text("git settings")
        count, backup = updater.install(self.staged, self.base, self.sha)
        self.assertEqual(count, 1)
        self.assertEqual((self.base / "main.py").read_text(), "new = True\n")
        self.assertEqual((backup / "main.py").read_text(), "old = True\n")
        for name in ("config.json", "capri.log", "my-notes.txt"):
            self.assertEqual((self.base / name).read_text(), "personal")
        self.assertEqual((self.base / ".git" / "config").read_text(), "git settings")
        self.assertEqual(updater.installed_version(self.base), self.sha)

    def test_failed_install_restores_all_changed_files_and_version(self):
        (self.staged / "module.py").write_text("new_module = True\n")
        (self.base / updater.VERSION_FILE).write_text("b" * 40)
        original_copy = updater._atomic_copy
        calls = []
        def fail(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("Disk full")
            return original_copy(source, destination)
        with patch("updater._atomic_copy", side_effect=fail), self.assertRaises(OSError):
            updater.install(self.staged, self.base, self.sha)
        self.assertEqual((self.base / "main.py").read_text(), "old = True\n")
        self.assertFalse((self.base / "module.py").exists())
        self.assertEqual(updater.installed_version(self.base), "b" * 40)

    def archive(self, entries):
        path = self.root / "update.zip"
        with zipfile.ZipFile(path, "w") as zipped:
            for name, content in entries:
                info = zipfile.ZipInfo("placeholder")
                info.filename = name
                zipped.writestr(info, content)
        return path

    def test_extract_rejects_paths_outside_archive_root(self):
        for name in ("root/../../outside.py", "/absolute.py", r"root\evil.py", "root/C:/evil.py"):
            with self.subTest(name=name):
                archive = self.archive([("root/main.py", "pass"), (name, "pass")])
                with self.assertRaises(ValueError):
                    updater.extract(archive, self.staged)

    def test_extract_excludes_config_logs_models_and_git(self):
        archive = self.archive([("root/main.py", "pass"), ("root/config.json", "personal"),
                                ("root/capri.log", "personal"), ("root/models/model.bin", "data"),
                                ("root/.git/config", "git"), ("root/new.py", "pass")])
        updater.extract(archive, self.staged)
        self.assertEqual(sorted(p.name for p in self.staged.iterdir()), ["main.py", "new.py"])

    def test_broken_python_update_is_rejected_before_install(self):
        archive = self.archive([("root/main.py", "def broken(" )])
        with self.assertRaises(SyntaxError):
            updater.extract(archive, self.staged)
        self.assertEqual((self.base / "main.py").read_text(), "old = True\n")

    def test_stop_app_only_touches_matching_python_in_target_folder(self):
        target = Mock()
        target.info = {"name": "pythonw.exe"}
        target.pid = 111
        target.cwd.return_value = str(self.base)
        target.cmdline.return_value = ["pythonw.exe", "main.py"]
        other = Mock()
        other.info = {"name": "pythonw.exe"}
        other.pid = 222
        other.cwd.return_value = str(self.root / "other")
        with patch("psutil.process_iter", return_value=[target, other]):
            updater._stop_app(self.base, 111)
        target.terminate.assert_called_once()
        other.terminate.assert_not_called()

    def test_update_voice_command_does_not_install_in_worker(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, str(self.base), None)
        with patch("actions.updater.start_update") as start:
            self.assertEqual(app.handle("обновись").action, "update")
            start.assert_not_called()
        with patch("actions.updater.latest_version", return_value=self.sha):
            reply = app.handle("проверь обновления")
        self.assertIn(self.sha[:7], reply.text)

    def test_second_update_cannot_run_while_first_is_active(self):
        lock = updater._acquire_lock(self.base)
        self.assertIsNotNone(lock)
        self.assertIsNone(updater._acquire_lock(self.base))
        lock.unlink()


if __name__ == "__main__":
    unittest.main()
