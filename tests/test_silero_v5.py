import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from capri.audio import voice_service as voice
from capri.config.defaults import DEFAULTS


class SileroV5Tests(unittest.TestCase):
    def test_model_is_v5_and_constructor_does_not_load_it_before_startup(self):
        with patch.object(voice,"silero_model") as load:
            speaker = voice.Speaker(DEFAULTS)
        load.assert_not_called()
        self.assertEqual(speaker.engine,"silero")
        self.assertTrue(voice.SILERO_URL.endswith('/v5_ru.pt'))
        self.assertEqual(speaker.silero_voice,"baya")

    def test_synthesis_uses_v5_prosody_profile_and_writes_audio(self):
        model = Mock()
        model.apply_tts.return_value = SimpleNamespace(numpy=lambda:np.sin(np.arange(12000)*.1).astype(np.float32)*.2)
        speaker = voice.Speaker(dict(DEFAULTS,voice_fx=0,voice_shift=.5,voice_glitch=0,voice_lively=False))
        with tempfile.TemporaryDirectory() as folder,patch.object(voice,"silero_model",return_value=model):
            path = Path(folder)/"voice.wav"
            speaker.render_silero("Test & voice.",str(path))
            self.assertGreater(path.stat().st_size,1000)
        args = model.apply_tts.call_args.kwargs
        self.assertEqual(args['speaker'],'baya')
        self.assertIn('&amp;',args['ssml_text'])
        self.assertIn('rate="89%"',args['ssml_text'])

    def test_cancelled_local_synthesis_does_not_fall_back_to_network(self):
        speaker = voice.Speaker(DEFAULTS)
        with patch.object(speaker,"render_silero",side_effect=InterruptedError),patch('edge_tts.Communicate') as network:
            with self.assertRaises(InterruptedError):
                speaker.render("Test.","unused.wav")
        network.assert_not_called()

    def test_waiting_for_model_lock_can_be_cancelled(self):
        speaker = voice.Speaker(DEFAULTS)
        speaker.stop_event.set()
        lock = threading.Lock()
        lock.acquire()
        with patch.object(voice,"silero_model",return_value=Mock()),patch.object(voice,"_silero_synthesis_lock",lock):
            with self.assertRaises(InterruptedError):
                speaker.render_silero("Test.","unused.wav")
        lock.release()

    def test_voice_cache_separates_speed_pitch_and_old_engine(self):
        speaker = voice.Speaker(DEFAULTS)
        original = speaker._cache_path("Test.")
        speaker.silero_speed = 1.1
        self.assertNotEqual(original,speaker._cache_path("Test."))
        speaker.silero_speed = .92
        speaker.silero_pitch = 'high'
        self.assertNotEqual(original,speaker._cache_path("Test."))
