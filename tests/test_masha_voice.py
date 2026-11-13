"""Native Russian Masha, bounded inference, pitch compensation and non-destructive glitches."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from capri.audio import kokoro_backend as kv
from capri.audio import voice_service as voice


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

    def test_double_mixes_complete_copy_with_exact_micro_delay(self):
        original = np.random.default_rng(3).uniform(-.9, .9, 72000).astype(np.float32)
        processed = voice.micro_double(original, amount=.4)
        delay = round(voice.FX_SR * .0015)
        expected = np.pad(original, (0, delay)) + .4 * np.pad(original, (delay, 0))
        np.testing.assert_allclose(processed, expected / 1.4, atol=1e-7)
        self.assertEqual(len(processed), len(original) + delay)
        self.assertLessEqual(float(np.max(abs(processed))), .901)

    def test_double_retains_final_speech_sample_and_delayed_tail(self):
        original = np.zeros(100, dtype=np.float32)
        original[-1] = 1
        processed = voice.micro_double(original, .5)
        self.assertAlmostEqual(float(processed[99]), 1 / 1.5)
        self.assertAlmostEqual(float(processed[-1]), .5 / 1.5)
        self.assertEqual(np.count_nonzero(processed), 2)

    def test_disabled_double_and_zero_pitch_preserve_all_samples(self):
        original = np.ones(1000, dtype=np.float32)
        self.assertIs(voice.micro_double(original, 0), original)
        self.assertIs(voice.pitch_shift(original, 0), original)
        empty = original[:0]
        self.assertIs(voice.micro_double(empty, 1), empty)

    def test_qwen_double_keeps_configured_volume_and_full_tail(self):
        speaker = voice.Speaker({"tts_engine": "qwen_clone", "voice_glitch": .4,
                                 "voice_volume": 20, "voice_fx": 0, "voice_shift": 0})
        original = np.ones(1000, dtype=np.float32) * .1
        with patch.object(speaker.qwen, "render"), \
                patch.object(voice, "decode", return_value=original), \
                patch.object(voice, "write_wav") as write:
            speaker.render("test", "out.wav")
        self.assertEqual(write.call_args.kwargs["volume"], speaker.volume)
        self.assertEqual(len(write.call_args.args[1]), 1036)

    def test_micro_double_invalidates_old_stutter_cache(self):
        speaker = voice.Speaker({"tts_engine": "kokoro", "voice_glitch": .25})
        current = speaker._cache_path("same phrase")
        with patch.object(voice, "VOICE_DOUBLE_VERSION", "old-stutter"):
            self.assertNotEqual(current, speaker._cache_path("same phrase"))

    def test_pitch_is_compensated_in_synthesis_speed(self):
        speaker = voice.Speaker({"tts_engine": "kokoro", "kokoro_voice": "masha", "voice_shift": 3,
                                 "voice_fx": .3, "voice_glitch": .25, "kokoro_speed": 1})
        with patch.object(speaker.kokoro, "render") as synth, \
                patch("capri.audio.voice_service.decode", return_value=np.ones(24000, np.float32) * .2), \
                patch("capri.audio.voice_service.write_wav"):
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
                patch("capri.audio.kokoro_backend.urllib.request.urlopen", return_value=io.BytesIO(payload)):
            kv.install_masha(Path(temp) / "voice")
            kv.verify_masha(Path(temp) / "voice")
            self.assertEqual((Path(temp) / "voice/model.onnx").read_bytes(), payload)

    def test_corrupt_download_does_not_replace_existing_model(self):
        good, bad = b"model data", b"wrong data"
        spec = {"model.onnx": ("model.onnx", len(good), hashlib.sha256(good).hexdigest())}
        with tempfile.TemporaryDirectory() as temp, patch.object(kv, "MASHA_FILES", spec), \
                patch("capri.audio.kokoro_backend.urllib.request.urlopen", return_value=io.BytesIO(bad)):
            folder = Path(temp) / "voice"
            folder.mkdir()
            (folder / "model.onnx").write_bytes(good)
            with self.assertRaises(ValueError):
                kv.install_masha(folder)
            self.assertEqual((folder / "model.onnx").read_bytes(), good)
