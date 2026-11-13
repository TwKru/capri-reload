"""Corpus review gates, library integrity, offline rendering and Colab resume scaffolding."""
import hashlib
import json
import tempfile
import threading
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from capri.audio.colab_backend import ColabVoiceClient, transport_options
from capri.audio.emotion_bank import EmotionBank
from capri.audio.qwen_backend import speech_chunks
from capri.audio.voice_library import VoiceLibrary
from capri.audio.voice_service import Speaker, decode
from tools.build_voice_colab import notebook
from tools.colab_train_voice import adapt
from tools.install_voice_library import install
from tools.voice_lab import prepare, training_manifest


def wav(path, seconds=1.2):
    x = np.sin(np.arange(int(24000 * seconds)) * 2 * np.pi * 440 / 24000) * .2
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes((x * 32767).astype("<i2").tobytes())


class VoiceColabTests(unittest.TestCase):
    def test_read_timeout_allows_long_running_synthesis(self):
        timeout = transport_options()["timeout"]
        self.assertGreater(timeout.read, 180)
        self.assertEqual(timeout.connect, 15)

    def test_pcm_wav_decode_preserves_samples_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.wav"
            wav(path)
            with wave.open(str(path), "rb") as source:
                expected = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2") / 32768
            with patch("capri.audio.voice_service._ffmpeg", side_effect=AssertionError("No subprocess needed")):
                np.testing.assert_array_equal(decode(path), expected)

    def test_short_first_chunk_retains_every_word(self):
        text = " ".join(["Проверяем скорость речи и сохраняем все окончания слов"] * 5) + "."
        chunks = list(speech_chunks(text, first_limit=60))
        self.assertEqual(" ".join(chunks), text)
        self.assertLessEqual(len(chunks[0]), 60)
        self.assertTrue(all(len(part) <= 110 for part in chunks))

    def test_colab_renders_next_chunk_while_first_chunk_plays(self):
        speaker = Speaker({"tts_engine": "qwen_clone"})
        speaker.engine = "colab"
        next_started = threading.Event()
        rendered, played = [], []
        text = " ".join(["Проверяем скорость речи и сохраняем все окончания слов"] * 5) + "."

        def render(part, destination):
            rendered.append(part)
            if len(rendered) == 2:
                next_started.set()
            return destination

        def play(path, *args):
            if not played:
                self.assertTrue(next_started.wait(2))
            played.append(path)
            return False

        with patch.object(speaker, "cached_render", side_effect=render), \
                patch("capri.audio.voice_service.play_mp3", side_effect=play):
            self.assertFalse(speaker._edge(text))
        self.assertLessEqual(len(rendered[0]), 60)
        self.assertEqual(" ".join(rendered), text)
        self.assertEqual(len(played), len(rendered))

    def test_timed_endpoint_records_separate_metrics_without_text(self):
        client = ColabVoiceClient("https://example.gradio.live", "secret", "voice")
        client.timed_api = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(client.downloads.name) / "timed.wav"
            wav(path)
            server = {"generation_seconds": .1, "write_seconds": .01}
            with patch.object(client, "_connect"), \
                    patch.object(client, "_call", return_value=(str(path), server)) as call:
                client.render("Привет!", str(Path(temp) / "output.wav"), threading.Event())
            self.assertEqual(call.call_args.args[0], "/speak_timed")
            self.assertEqual(client.last_metrics["generation_seconds"], .1)
            self.assertGreaterEqual(client.last_metrics["transport_queue_seconds"], 0)
            self.assertNotIn("text", client.last_metrics)
        client.downloads.cleanup()

    def test_remote_cancel_cancels_queued_generation(self):
        client = ColabVoiceClient("https://example.gradio.live", "secret", "voice")
        job = Mock()
        job.done.return_value = False
        client.client = Mock()
        client.client.submit.return_value = job
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            client._call("/speak", cancel, "Привет")
        job.cancel.assert_called_once()
        self.assertIsNone(client.job)
        client.downloads.cleanup()

    def test_colab_download_is_rendered_and_removed(self):
        client = ColabVoiceClient("https://example.gradio.live", "secret", "voice")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(client.downloads.name) / "sample.wav"
            wav(path)
            with patch.object(client, "_connect"), patch.object(client, "_call", return_value=str(path)):
                client.render("Привет!", str(Path(temp) / "output.wav"), threading.Event(), volume=20)
            self.assertTrue((Path(temp) / "output.wav").exists())
            self.assertFalse(path.exists())
        client.downloads.cleanup()

    def test_colab_rejects_insecure_urls_before_auth(self):
        with self.assertRaises(ValueError):
            ColabVoiceClient("http://example.test", "secret", "voice")

    def test_emotion_bank_does_not_immediately_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "giggle").mkdir()
            wav(root / "giggle/a.wav")
            wav(root / "giggle/b.wav")
            bank = EmotionBank(root)
            first, rest = bank.prefix("Хи-хи! Привет.")
            second, _ = bank.prefix("[хихикает] Привет.")
            self.assertNotEqual(first, second)
            self.assertEqual(rest, "Привет.")
            self.assertEqual(bank.prefix("[вздыхает] Привет."), (None, "[вздыхает] Привет."))

    def test_huff_prefixes_and_angry_reaction_cooldown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "huff").mkdir()
            wav(root / "huff/a.wav")
            bank = EmotionBank(root)
            for text in ("Хмф! Ну ладно.", "hmph! Ну ладно.", "[фыркает] Ну ладно."):
                audio, remaining = bank.prefix(text)
                self.assertEqual(audio, root / "huff/a.wav")
                self.assertEqual(remaining, "Ну ладно.")
            self.assertEqual(bank.angry_prefix("Ну ладно.", 100), "Хмф! Ну ладно.")
            self.assertEqual(bank.angry_prefix("Другой ответ.", 101), "Другой ответ.")
            self.assertEqual(bank.angry_prefix("Другой ответ.", 121), "Хмф! Другой ответ.")
            self.assertEqual(bank.prefix("Пфайфер"), (None, "Пфайфер"))

    def test_giggle_plays_recording_then_synthesizes_remaining_words(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "giggle").mkdir()
            wav(root / "giggle/a.wav")
            speaker = Speaker({"tts_engine": "qwen_clone", "voice_emotions_path": str(root),
                               "voice_fx": 0, "voice_glitch": .45, "voice_shift": .8})
            with patch("capri.audio.voice_service.play_mp3", return_value=False) as play, \
                    patch.object(speaker, "_edge", return_value=False) as speak:
                speaker.say("Хи-хи! Проверим?")
            play.assert_called_once()
            speak.assert_called_once_with("Проверим?")

    def library(self, root):
        wav(root / "speech.wav")
        content = {"version": 1, "processing": "raw", "entries": [
            {"text": "Привет!", "audio": "speech.wav",
             "sha256": hashlib.sha256((root / "speech.wav").read_bytes()).hexdigest()}]}
        (root / "manifest.json").write_text(json.dumps(content), encoding="utf-8")
        return content

    def test_notebook_code_cells_compile_and_have_no_credentials(self):
        document = notebook()
        for cell in document["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "notebook-cell", "exec")
        text = json.dumps(document)
        self.assertNotIn("config.json", text)
        self.assertIn("latest.json", text)

    def test_corpus_deduplicates_and_requires_review_before_training(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "corpus"
            source.mkdir()
            wav(source / "a.wav")
            (source / "duplicate.wav").write_bytes((source / "a.wav").read_bytes())
            records = prepare(source, output)
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["reviewed"])
            with self.assertRaises(ValueError):
                training_manifest(output, root / "train.jsonl")
            (source / "a.txt").write_text("Точный текст.", encoding="utf-8")
            prepare(source, output)
            self.assertEqual(training_manifest(output, root / "train.jsonl"), 1)
            item = json.loads((root / "train.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(item["text"], "Точный текст.")
            self.assertEqual(item["audio"], item["ref_audio"])

    def test_empty_corpus_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                prepare(Path(temp), Path(temp) / "out")

    def test_library_import_and_render_skip_neural_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.library(root)
            archive = root / "library.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for name in ("manifest.json", "speech.wav"):
                    output.write(root / name, name)
            destination = install(archive, root / "installed", activate=False)
            speaker = Speaker({"tts_engine": "qwen_clone", "voice_library_path": str(destination),
                               "voice_shift": .8, "voice_glitch": .45, "voice_fx": 0})
            self.assertIsNotNone(speaker.voice_library.find("  Привет!  "))
            before = speaker._cache_path("Привет!")
            speaker.qwen.render = Mock(side_effect=AssertionError("Must use the library"))
            speaker.render("Привет!", str(root / "result.wav"))
            self.assertTrue((root / "result.wav").exists())
            speaker.voice_library = VoiceLibrary()
            self.assertNotEqual(before, speaker._cache_path("Привет!"))

    def test_unknown_text_falls_back_to_local_synthesis(self):
        speaker = Speaker({"tts_engine": "qwen_clone", "voice_fx": 0, "voice_glitch": 0,
                           "voice_shift": 0})
        with patch.object(speaker.qwen, "render") as synth:
            speaker.render("Новая фраза", "result.wav")
            synth.assert_called_once()

    def test_corrupt_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.library(root)
            (root / "speech.wav").write_bytes(b"broken")
            with self.assertRaises(ValueError):
                VoiceLibrary(root)

    def test_archive_cannot_escape_install_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escaped.txt", "bad")
            with self.assertRaises(ValueError):
                install(archive, root / "installed", activate=False)
            self.assertFalse((root / "escaped.txt").exists())

    def test_training_patch_fails_closed_for_unknown_upstream(self):
        with self.assertRaises(ValueError):
            adapt("changed upstream trainer")


if __name__ == "__main__":
    unittest.main()
