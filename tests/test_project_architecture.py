"""Пакетная структура, сохранность путей и новые точки запуска."""
import ast
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from capri.core.paths import APP_ROOT, PRIVATE_FILENAMES, PROJECT_ROOT, RESOURCE_ROOT
from capri.updates import source_updater
from tools import package_source_release


class ProjectArchitectureTests(unittest.TestCase):
    def test_only_application_entry_point_remains_at_root(self):
        self.assertEqual({path.name for path in PROJECT_ROOT.glob("*.py")},{"main.py"})

    def test_importing_package_does_not_start_windows_application(self):
        result = subprocess.run([sys.executable,"-c",
            "import capri,sys; assert 'capri.app.controller' not in sys.modules; assert 'PySide6' not in sys.modules"],
            cwd=PROJECT_ROOT,capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_runtime_paths_do_not_depend_on_module_folder_or_cwd(self):
        self.assertEqual(PROJECT_ROOT/"main.py",Path(__file__).resolve().parents[1]/"main.py")
        self.assertEqual(APP_ROOT,PROJECT_ROOT)
        self.assertTrue((RESOURCE_ROOT/"assets/ui/chevron-down.svg").is_file())
        self.assertTrue((RESOURCE_ROOT/"docs/voice_commands.md").is_file())

    def test_foundation_and_storage_do_not_import_ui_or_application(self):
        for folder in ("core","storage"):
            for path in (PROJECT_ROOT/"capri"/folder).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    modules = [alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module or ""] if isinstance(node,ast.ImportFrom) else []
                    for module in modules:
                        self.assertFalse(module.startswith(("capri.ui","capri.app","capri.ai","PySide6")),f"{path}: {module}")

    def test_package_initializers_have_no_startup_side_effects(self):
        for path in (PROJECT_ROOT/"capri").rglob("__init__.py"):
            statements=ast.parse(path.read_text(encoding="utf-8")).body
            self.assertTrue(all(isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)
                                for node in statements),str(path))

    def test_renamed_modules_are_importable_without_flat_module_shims(self):
        names=("capri.config.settings","capri.ai.providers.openai_provider","capri.ai.providers.gemini_provider",
               "capri.audio.kokoro_backend","capri.automation.desktop_agent","capri.ui.dialogs.ai_settings",
               "capri.updates.source_updater","tools.install_vosk_model","tools.package_source_release")
        for name in names:
            self.assertIsNotNone(importlib.util.find_spec(name),name)

    def test_private_filenames_are_unchanged_and_shared_by_packagers(self):
        expected={"config.json","memory.json","me.md","personality.md","jobs.sqlite"}
        self.assertTrue(expected <= PRIVATE_FILENAMES)
        self.assertTrue(PRIVATE_FILENAMES <= source_updater.PROTECTED_FILES)
        self.assertTrue(PRIVATE_FILENAMES <= package_source_release.SKIP_FILES)

    def test_voice_worker_can_be_started_as_a_module(self):
        result=subprocess.run([sys.executable,"-m","capri.audio.kokoro_backend","--help"],
                              cwd=PROJECT_ROOT,capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("--worker",result.stdout)

    def test_updater_recognizes_module_launch_but_not_another_project(self):
        process=Mock(pid=123)
        process.info={"pid":123,"name":"python.exe"}
        process.cwd.return_value=str(PROJECT_ROOT)
        process.cmdline.return_value=[sys.executable,"-m","capri"]
        with patch("psutil.process_iter",return_value=[process]):
            source_updater._stop_app(PROJECT_ROOT,123)
        process.terminate.assert_called_once()
        process.terminate.reset_mock()
        process.cwd.return_value=str(PROJECT_ROOT.parent)
        with patch("psutil.process_iter",return_value=[process]):
            source_updater._stop_app(PROJECT_ROOT,123)
        process.terminate.assert_not_called()
