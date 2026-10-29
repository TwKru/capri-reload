"""Гамма: проверки без изменения изображения на настоящем мониторе."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import gamma
from actions import Actions, parse_gamma_value


class FakeDevice:
    name = r"\\.\DISPLAY1"

    def __init__(self):
        self.values = gamma.make_ramp(1.1)
        self.fail = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.values.copy()

    def write(self, values):
        self.values = values.copy()

    def write_checked(self, values):
        self.write(values)
        if self.fail:
            raise OSError("Driver refused gamma")


class GammaTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = pathlib.Path(folder.name) / "gamma_backup.json"
        self.device = FakeDevice()
        for replacement in (patch.object(gamma, "_backup_path", return_value=str(self.path)),
                            patch.object(gamma, "_GammaDevice", return_value=self.device)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_night_ramp_is_monotone_equal_rgb_and_keeps_endpoints(self):
        ramp = gamma.make_ramp(gamma.MAX_GAMMA)
        self.assertEqual(len(ramp), 768)
        self.assertEqual(ramp[:256], ramp[256:512])
        self.assertEqual(ramp[:256], ramp[512:])
        self.assertEqual((ramp[0], ramp[255]), (0, 65535))
        self.assertEqual(ramp[:256], sorted(ramp[:256]))
        self.assertGreater(ramp[64], 64 * 257)
        self.assertTrue(all(0 <= value <= 65535 and abs(value - i * 257) < 32768
                            for i, value in enumerate(ramp[:256])))

    def test_backup_is_preserved_across_repeated_night_and_restored(self):
        original = self.device.read()
        gamma.night()
        self.assertEqual(self.device.read(), gamma.make_ramp(gamma.MAX_GAMMA))
        gamma.night()
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved[self.device.name], original)
        self.assertTrue(gamma.restore())
        self.assertEqual(self.device.read(), original)
        self.assertEqual(json.loads(self.path.read_text()), {})

    def test_failure_rolls_back_and_keeps_backup(self):
        original = self.device.read()
        self.device.fail = True
        with self.assertRaises(OSError):
            gamma.night()
        self.assertEqual(self.device.read(), original)
        self.assertEqual(json.loads(self.path.read_text())[self.device.name], original)

    def test_explicit_gamma_changes_preserve_original_calibration(self):
        original = self.device.read()
        gamma.set_gamma(2.5)
        self.assertEqual(self.device.read(), gamma.make_ramp(2.5))
        gamma.set_gamma(1.0)
        self.assertEqual(self.device.read(), gamma.make_ramp(1.0))
        self.assertTrue(gamma.restore())
        self.assertEqual(self.device.read(), original)

    def test_invalid_values_do_not_touch_display_or_backup(self):
        original = self.device.read()
        for value in (0, -1, gamma.MAX_GAMMA + 1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gamma.set_gamma(value)
            self.assertEqual(self.device.read(), original)
            self.assertFalse(self.path.exists())

    def test_cannot_change_gamma_without_saving_original(self):
        original = self.device.read()
        with patch.object(gamma, "_save_backup", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                gamma.night()
        self.assertEqual(self.device.read(), original)

    def test_restore_without_backup_does_not_reset_calibration(self):
        original = self.device.read()
        self.assertFalse(gamma.restore())
        self.assertEqual(self.device.read(), original)

    def test_corrupt_backup_is_not_overwritten(self):
        self.path.write_text('{"display": [1, 2]}')
        original = self.device.read()
        with self.assertRaises(ValueError):
            gamma.night()
        self.assertEqual(self.device.read(), original)
        self.assertEqual(self.path.read_text(), '{"display": [1, 2]}')

    def test_false_driver_success_is_detected(self):
        # Вызываем настоящий алгоритм проверки на подставном устройстве.
        native_class = self.native_class
        fake = Mock()
        fake.read.return_value = gamma.make_ramp(1.0)
        with self.assertRaises(OSError):
            native_class.write_checked(fake, gamma.make_ramp(gamma.MAX_GAMMA))

    native_class = gamma._GammaDevice


class GammaCommandTests(unittest.TestCase):
    def test_numeric_and_spoken_gamma_commands(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        commands = (("поставь гамму 2,5", 2.5), ("гамма 1.25", 1.25),
                    ("гамма на три", 3.0), ("установи гамму два с половиной", 2.5),
                    ("гамма две целых пять десятых", 2.5),
                    ("поставь гамму одну целую пять десятых", 1.5),
                    ("гамма ноль точка семь", 0.7), ("гамма два пять", 2.5),
                    ("гамма две целых пять сотых", 2.05), ("гамма полтора", 1.5))
        for command, expected in commands:
            with self.subTest(command=command), patch("actions.gamma.set_gamma") as set_gamma:
                reply = app.handle(command)
                set_gamma.assert_called_once_with(expected)
                self.assertTrue(app.is_fast_command(command))
                self.assertIn("Гамма ", reply.text)
        for command in ("гамма ноль", "гамма минус один", "гамма 100", "гамма сколько-нибудь"):
            with self.subTest(command=command), patch("actions.gamma.set_gamma") as set_gamma:
                app.handle(command)
                set_gamma.assert_not_called()

    def test_fractional_parser_keeps_decimal_precision(self):
        self.assertAlmostEqual(parse_gamma_value("одна целая ноль пять"), 1.05)
        self.assertAlmostEqual(parse_gamma_value("одна целая двадцать пять сотых"), 1.25)
        with self.assertRaises(ValueError):
            parse_gamma_value("две целых сто десятых")

    def test_command_routes_and_fast_recognition(self):
        with patch("actions.AppIndex.build"):
            app = Actions({}, ".", None)
        for command in ("ночь", "включи ночной режим", "гамма на максимум"):
            with self.subTest(command=command), patch("actions.gamma.night") as night:
                app.handle(command)
                night.assert_called_once()
                self.assertTrue(app.is_fast_command(command))
        for command in ("день", "верни гамму", "выключи ночной режим"):
            with self.subTest(command=command), patch("actions.gamma.restore", return_value=True) as restore:
                app.handle(command)
                restore.assert_called_once()
        with patch("actions.gamma.night", side_effect=OSError("Driver refused")):
            self.assertIn("Не смогла", app.handle("ночь").text)


if __name__ == "__main__":
    unittest.main()
