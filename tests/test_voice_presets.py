"""Reference presets preserve the original voice and keep processed caches separate."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from capri.audio.qwen_backend import QwenClient
from capri.audio.qwen_cli_backend import QwenCliClient
from tools.install_voice_preset import install


class VoicePresetTests(unittest.TestCase):
    def test_default_and_named_presets_read_separate_reference_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            preset = root/"presets/capri2"
            preset.mkdir(parents=True)
            (root/"voice-profile.json").write_text('{"sha256":"original"}')
            (preset/"voice-profile.json").write_text('{"sha256":"new"}')
            old = QwenCliClient(folder=root)
            new = QwenCliClient(folder=root,voice_preset="capri2",processing="clean")
            self.assertEqual(old.reference_folder,root)
            self.assertEqual(new.reference_folder,preset)
            self.assertEqual(old.profile_id,"original")
            self.assertEqual(new.profile_id,"new")
            self.assertNotEqual(old.cache_revision,new.cache_revision)

    def test_preset_name_cannot_escape_voice_folder(self):
        for name in ("../other","C:/other","a/b",""):
            with self.assertRaises(ValueError):
                QwenCliClient(voice_preset=name)

    def test_clean_voice_uses_selected_reference_and_skips_b_layers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = QwenCliClient(folder=root,voice_preset="capri2",processing="clean")
            child = Mock()
            child.poll.return_value = 0
            child.returncode = 0
            args = []
            def launch(value):
                args.extend(value)
                client.process = child
            pcm = np.sin(np.arange(24000)*.1).astype(np.float32)*.1
            with patch.object(client,"verify_files"),patch.object(client,"launch",side_effect=launch), \
                 patch("capri.audio.voice_service.decode",return_value=pcm), \
                 patch("capri.audio.clone_effects.process_layers") as layers, \
                 patch("capri.audio.voice_service.write_wav") as write:
                client.render("Тест.",str(root/"out.wav"),threading.Event())
            self.assertEqual(args[args.index("--tts-speaker-file")+1],str(root/"presets/capri2/voice-reference.wav"))
            layers.assert_not_called()
            self.assertEqual(len(write.call_args.args[1]),len(pcm))

    def test_install_preserves_original_files_and_hashes_new_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root/"voice-reference.wav"
            original.write_bytes(b"keep original")
            audio = np.sin(np.arange(48000)*.1).astype(np.float32)*.1
            with patch("capri.audio.voice_service.decode",return_value=audio):
                target = install("unused.mp3","capri2",folder=root)
            self.assertEqual(original.read_bytes(),b"keep original")
            profile = json.loads((target/"voice-profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["sha256"],hashlib.sha256((target/"voice-reference.wav").read_bytes()).hexdigest())
            self.assertEqual(profile["duration_seconds"],2.)
            self.assertEqual(QwenClient(folder=root,reference_folder=target).profile_id,profile["sha256"])
