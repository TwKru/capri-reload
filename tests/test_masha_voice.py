"""Native Russian Masha, bounded inference, pitch compensation and non-destructive glitches."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import kokoro_voice as kv
import voice


class MashaVoiceTests(unittest.TestCase):
    def test_long_phoneme_input_is_not_truncated_and_speed_is_float(self):
        session = Mock()
        session.run.return_value = [np.concatenate((np.zeros(2400), np.ones(2400) * .2, np.zeros(2400)))]
        style = np.ones((510, 256), np.float32)
        audio, rate = kv.generate_masha(session, style, {"a": 43}, "a" * 1100, .84)
        self.assertEqual(rate, 24000)
        self.assertTrue(np.isfinite(audio).all())
        inputs = [call.args[1] for call in session.run.call_args_list]
        self.assertEqual(sum(item["input_ids"].shape[1] - 2 for item in inputs), 1100)
        for item in inputs:
            self.assertLessEqual(item["input_ids"].shape[1], 482)
            self.assertEqual(item["speed"].dtype, np.float32)
            self.assertEqual(item["style"].shape, (1, 256))

    def test_glitches_insert_audio_without_removing_original_samples(self):
        original = np.linspace(-.9, .9, 72000, dtype=np.float32)
        processed = voice.light_stutter(original, amount=1, seed=3)
        self.assertGreater(len(processed), len(original))
        self.assertLessEqual(len(processed) - len(original), int(voice.FX_SR * .031))
        self.assertTrue(np.isfinite(processed).all())
        position = 0
        for sample in processed:
            if position < len(original) and sample == original[position]:
                position += 1
        self.assertEqual(position, len(original))
        self.assertLessEqual(float(np.max(abs(processed))), .901)

    def test_short_or_disabled_glitches_leave_audio_alone(self):
        original = np.ones(1000, dtype=np.float32)
        self.assertIs(voice.light_stutter(original, 1), original)
        original = np.ones(72000, dtype=np.float32)
        self.assertIs(voice.light_stutter(original, 0), original)

    def test_pitch_is_compensated_in_synthesis_speed(self):
        speaker = voice.Speaker({"tts_engine": "kokoro", "kokoro_voice": "masha", "voice_shift": 3,
                                 "voice_fx": .3, "voice_glitch": .25, "kokoro_speed": 1})
        with patch.object(speaker.kokoro, "render") as synth, \
                patch("voice.decode", return_value=np.ones(24000, np.float32) * .2), \
                patch("voice.write_wav"):
            speaker.render("Мой голос стал выше.", "out.wav")
        self.assertEqual(speaker.kokoro.variant, "masha")
        self.assertAlmostEqual(synth.call_args.kwargs["speed"], 2 ** (-3 / 12))

    def test_masha_and_new_glitches_cannot_reuse_old_voice_cache(self):
        base = {"tts_engine": "kokoro", "voice_shift": 3, "voice_fx": .3}
        old = voice.Speaker(dict(base, kokoro_voice="capri"))
        masha = voice.Speaker(dict(base, kokoro_voice="masha", voice_glitch=.25))
        clean = voice.Speaker(dict(base, kokoro_voice="masha", voice_glitch=0))
        self.assertEqual(len({s._cache_path("Привет") for s in (old, masha, clean)}), 3)

    def test_silent_model_output_is_rejected(self):
        model = Mock()
        model.run.return_value = [np.zeros(24000, np.float32)]
        with self.assertRaises(ValueError):
            kv.generate_masha(model, np.ones((510, 256), np.float32), {"a": 1}, "a", 1)

    def test_native_model_download_verifies_all_files_before_installing(self):
        payload = b"pinned model"
        spec = {"model.onnx": ("model.onnx", len(payload), hashlib.sha256(payload).hexdigest())}
        with tempfile.TemporaryDirectory() as temp, patch.object(kv, "MASHA_FILES", spec), \
                patch("kokoro_voice.urllib.request.urlopen", return_value=io.BytesIO(payload)):
            kv.install_masha(Path(temp) / "voice")
            kv.verify_masha(Path(temp) / "voice")
            self.assertEqual((Path(temp) / "voice/model.onnx").read_bytes(), payload)

    def test_corrupt_download_does_not_replace_existing_model(self):
        good, bad = b"model data", b"wrong data"
        spec = {"model.onnx": ("model.onnx", len(good), hashlib.sha256(good).hexdigest())}
        with tempfile.TemporaryDirectory() as temp, patch.object(kv, "MASHA_FILES", spec), \
                patch("kokoro_voice.urllib.request.urlopen", return_value=io.BytesIO(bad)):
            folder = Path(temp) / "voice"
            folder.mkdir()
            (folder / "model.onnx").write_bytes(good)
            with self.assertRaises(ValueError):
                kv.install_masha(folder)
            self.assertEqual((folder / "model.onnx").read_bytes(), good)
