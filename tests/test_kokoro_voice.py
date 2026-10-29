"""Voice pack authenticity, Russian phonemes, cancellation and backend routing."""
import hashlib
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

import kokoro_voice as kv
import voice


class VoicePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, extra=None):
        archive = self.root / "pack.zip"
        files = {"model.onnx": b"model", "voices.bin": b"voices", "tokens.txt": b"tokens",
                 "licenses/README.txt": b"terms", "untrusted.dll": b"never unpack"}
        files.update(extra or {})
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in kv.HASHES}
        return archive, hashes

    def test_install_verifies_archive_and_omits_executable_libraries(self):
        archive, hashes = self.bundle()
        folder = self.root / "installed"
        with patch.object(kv, "HASHES", hashes), patch.object(kv, "PACK_SIZE", archive.stat().st_size), \
                patch.object(kv, "PACK_SHA", hashlib.sha256(archive.read_bytes()).hexdigest()):
            kv.install_pack(archive, folder)
            kv.verify_pack(folder)
            (folder / "voices.bin").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                kv.verify_pack(folder)
        self.assertTrue((folder / "licenses/README.txt").is_file())
        self.assertFalse((folder / "untrusted.dll").exists())

    def test_invalid_hash_cannot_write_installed_files(self):
        archive, _ = self.bundle()
        folder = self.root / "installed"
        with patch.object(kv, "PACK_SIZE", archive.stat().st_size), self.assertRaises(ValueError):
            kv.install_pack(archive, folder)
        self.assertFalse(folder.exists())

    def test_authenticated_archive_still_rejects_traversal(self):
        archive, hashes = self.bundle({"../escape.txt": b"bad"})
        with patch.object(kv, "HASHES", hashes), patch.object(kv, "PACK_SIZE", archive.stat().st_size), \
                patch.object(kv, "PACK_SHA", hashlib.sha256(archive.read_bytes()).hexdigest()), \
                self.assertRaises(ValueError):
            kv.install_pack(archive, self.root / "installed")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_russian_sounds_are_mapped_instead_of_dropped(self):
        vocab = dict.fromkeys("lzʲʒɨ .", 1)
        self.assertEqual(kv.adapt_phonemes("ɭɫʑʐy.", vocab), "llzʲʒɨ.")
        self.assertEqual(kv.adapt_phonemes("y", {"y": 1}, russian=False), "y")


class LocalVoiceClientTests(unittest.TestCase):
    def make_client(self):
        client = kv.KokoroClient()
        process = Mock()
        process.poll.return_value = None
        client.process = process
        client.results = queue.Queue()
        self.addCleanup(client.close)
        return client, process

    def test_worker_crash_is_contained_and_reaped(self):
        client, process = self.make_client()
        client.results.put(None)
        with self.assertRaises(RuntimeError):
            client.render("hello", "voice.wav")
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        self.assertIsNone(client.process)

    def test_stop_cancels_and_reaps_worker(self):
        client, process = self.make_client()
        cancel = threading.Event()
        timer = threading.Timer(.1, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(InterruptedError):
            client.render("hello", "voice.wav", cancel=cancel)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_success_keeps_worker_alive_and_sends_text_as_data(self):
        client, process = self.make_client()
        def sent():
            client.results.put({"ok": True})
        process.stdin.flush.side_effect = sent
        self.assertEqual(client.render("Привет; $(noop)", "voice.wav"), "voice.wav")
        payload = json.loads(process.stdin.write.call_args.args[0])
        self.assertEqual(payload["text"], "Привет; $(noop)")
        process.kill.assert_not_called()

    def test_timeout_stops_helper(self):
        client, process = self.make_client()
        with self.assertRaises(TimeoutError):
            client.render("hello", "voice.wav", timeout=-1)
        process.kill.assert_called_once()

    def test_all_text_uses_local_voice_without_online_requests(self):
        speaker = voice.Speaker({"tts_engine": "kokoro"})
        with patch.object(speaker.kokoro, "render", return_value="voice.wav") as render, \
                patch("edge_tts.Communicate") as online:
            for text in ("Привет.", "Готово. Заебись."):
                self.assertEqual(speaker.render(text, "voice.wav"), "voice.wav")
        self.assertEqual(render.call_count, 2)
        online.assert_not_called()
        self.assertEqual(speaker.shift, 0)
        self.assertEqual(speaker.fx, 0)

    def test_stop_during_synthesis_does_not_switch_to_windows_or_mark_failure(self):
        speaker = voice.Speaker({"tts_engine": "kokoro"})
        with patch("voice.os.path.isfile", return_value=False), \
                patch.object(speaker, "_edge", side_effect=InterruptedError), \
                patch.object(speaker, "_sapi") as fallback:
            self.assertTrue(speaker.say("Привет."))
        fallback.assert_not_called()
        self.assertEqual(speaker._edge_failures, 0)
