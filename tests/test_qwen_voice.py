import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from capri.audio import voice_service as voice
from capri.audio.clone_effects import process_layers, reduce_background, spectral_profile
from capri.audio.qwen_backend import QwenClient, speech_chunks
from capri.audio.qwen_cli_backend import QwenCliClient


class ClonedVoiceTests(unittest.TestCase):
    def test_approved_generator_cache_cannot_reuse_server_speech(self):
        speaker = voice.Speaker({'tts_engine':'qwen_clone'})
        self.assertIsInstance(speaker.qwen, QwenCliClient)
        approved = speaker._cache_path('Слушаю.')
        speaker.qwen.cache_revision = 'server-v1'
        self.assertNotEqual(approved, speaker._cache_path('Слушаю.'))

    def test_approved_cli_cancel_kills_native_process_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            client = QwenCliClient(folder=folder)
            cancel = threading.Event()
            child = Mock()
            child.poll.return_value = None
            def launch(args):
                client.process = child
                cancel.set()
            with patch.object(client, 'verify_files'), patch.object(client, 'launch', side_effect=launch):
                with self.assertRaises(InterruptedError):
                    client.render('Проверка.', 'unused.wav', cancel)
            child.kill.assert_called_once()
            self.assertTrue(client.lock.acquire(blocking=False))
            client.lock.release()
    def test_long_replies_preserve_every_word_and_have_bounded_chunks(self):
        text = ('Первое предложение. ' + 'длинное объяснение ' * 60 + 'Последнее слово.')
        chunks = list(speech_chunks(text))
        self.assertEqual(' '.join(chunks), ' '.join(text.split()))
        self.assertTrue(all(len(chunk) <= 110 for chunk in chunks))

    def test_cancel_before_start_never_launches_worker_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            client = QwenClient(folder=folder)
            cancel = threading.Event()
            cancel.set()
            with patch('subprocess.Popen') as process:
                with self.assertRaises(InterruptedError):
                    client.render('Слушаю.', 'unused.wav', cancel)
            process.assert_not_called()

    def test_stop_during_native_request_kills_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            client = QwenClient(folder=folder)
            cancel, released, started = threading.Event(), threading.Event(), threading.Event()
            def request(*args):
                started.set()
                released.wait(2)
                raise OSError('Worker terminated')
            def close():
                released.set()
            def interrupt():
                started.wait(2)
                cancel.set()
            thread = threading.Thread(target=interrupt)
            thread.start()
            with patch.object(client, '_ensure'), patch.object(client, '_request', side_effect=request), \
                    patch.object(client, 'close', side_effect=close) as kill:
                with self.assertRaises(InterruptedError):
                    client.render('Проверка.', 'unused.wav', cancel)
            thread.join(2)
            kill.assert_called_once()
            self.assertTrue(client.lock.acquire(blocking=False))
            client.lock.release()

    def test_clone_cancel_never_switches_to_online_synthesis(self):
        speaker = voice.Speaker({'tts_engine':'qwen_clone'})
        with patch.object(speaker.qwen, 'render', side_effect=InterruptedError), \
                patch('edge_tts.Communicate') as network:
            with self.assertRaises(InterruptedError):
                speaker.render('Проверка.', 'unused.wav')
        network.assert_not_called()

    def test_new_recordings_invalidate_cached_voice(self):
        speaker = voice.Speaker({'tts_engine':'qwen_clone'})
        before = speaker._cache_path('Слушаю.')
        speaker.qwen.profile_id = 'another-reference'
        self.assertNotEqual(before, speaker._cache_path('Слушаю.'))

    def test_next_phrase_synthesizes_while_current_audio_plays(self):
        speaker = voice.Speaker({'tts_engine':'qwen_clone'})
        next_started = threading.Event()
        rendered, played = [], []
        def render(text, dst):
            rendered.append(text)
            if len(rendered) == 2:
                next_started.set()
            return dst
        def play(path, *args):
            if not played:
                self.assertTrue(next_started.wait(2))
            played.append(path)
            return False
        text = 'Первое предложение. Второе предложение. Последнее предложение.'
        with patch.object(speaker, 'cached_render', side_effect=render), \
                patch.object(voice, 'play_mp3', side_effect=play):
            self.assertFalse(speaker._qwen_sentences(text))
        self.assertEqual(rendered, list(speech_chunks(text)))
        self.assertEqual(len(played), 3)
        self.assertFalse(speaker.playing)

    def test_real_layer_processing_preserves_duration_and_valid_samples(self):
        # A gap and a final tone exercise timing/ending preservation in Rubber Band.
        audio = np.zeros(24000, dtype=np.float32)
        tone = np.sin(np.arange(7200) * (2*np.pi*240/24000)) * .15
        audio[:7200] = tone
        audio[-7200:] = tone
        out = process_layers(audio, spectral_profile(audio), voice._ffmpeg())
        self.assertEqual(len(out), len(audio))
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertGreater(np.sqrt(np.mean(out[-2000:]**2)), .02)
        self.assertLess(np.sqrt(np.mean(out[11000:12500]**2)), .02)

    def test_cancelled_layers_terminate_child(self):
        cancel = threading.Event()
        cancel.set()
        child = Mock()
        child.poll.return_value = None
        with patch('subprocess.Popen', return_value=child):
            with self.assertRaises(InterruptedError):
                process_layers(np.zeros(24000), np.ones(1025), 'ffmpeg', cancel)
        child.kill.assert_called_once()
        child.communicate.assert_called_once()

    def test_background_noise_is_reduced_without_cutting_faint_consonants(self):
        rng = np.random.default_rng(17)
        x = rng.normal(0, .002, 72000).astype(np.float32)
        t = np.arange(24000) / 24000
        x[24000:48000] += (.15*np.sin(2*np.pi*240*t)).astype(np.float32)
        # A weak high-frequency consonant after the voice must survive.
        consonant = slice(49000, 53000)
        x[consonant] += (.025*np.sin(2*np.pi*6500*np.arange(4000)/24000)).astype(np.float32)
        y = reduce_background(x)
        rms = lambda a: float(np.sqrt(np.mean(a**2)))
        self.assertEqual(len(y), len(x))
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertLess(rms(y[4000:16000]), rms(x[4000:16000])*.45)
        self.assertGreater(rms(y[28000:44000]), rms(x[28000:44000])*.95)
        self.assertGreater(rms(y[consonant]), rms(x[consonant])*.8)
        # During speech the samples (and therefore pitch/formants) are untouched.
        np.testing.assert_allclose(y[28000:44000], x[28000:44000], rtol=0, atol=2e-8)
        np.testing.assert_allclose(y[consonant], x[consonant], rtol=0, atol=2e-8)

    def test_denoise_handles_silence_and_short_audio_without_nan(self):
        for n in (0, 32, 1000, 4800):
            y = reduce_background(np.zeros(n, np.float32))
            self.assertEqual(len(y), n)
            self.assertTrue(np.all(np.isfinite(y)))
