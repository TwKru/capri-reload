"""CUDA arguments, runtime integrity and CPU compatibility without GPU execution."""
import hashlib
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from capri.audio.qwen_backend import QwenClient
from capri.audio.qwen_cli_backend import CUDA_FOLDER, QwenCliClient
from tools import install_qwen_cuda


class CudaVoiceTests(unittest.TestCase):
    def test_auto_selects_installed_cuda_and_keeps_cpu_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(QwenCliClient(folder=root,device="auto").device,"cpu")
            (root/CUDA_FOLDER).mkdir()
            (root/CUDA_FOLDER/"ggml-cuda.dll").touch()
            gpu = QwenCliClient(folder=root,device="auto")
            cpu = QwenCliClient(folder=root,device="cpu")
            self.assertEqual(gpu.device,"cuda")
            self.assertEqual(cpu.device,"cpu")
            self.assertNotEqual(gpu.cache_revision,cpu.cache_revision)
            self.assertEqual(gpu.process_env["GGML_CUDA_DISABLE_GRAPHS"],"1")
            self.assertFalse(hasattr(cpu,"process_env"))

    def test_cuda_offloads_layers_and_bounds_context_without_changing_voice(self):
        for device in ("cpu","cuda"):
            with self.subTest(device=device),tempfile.TemporaryDirectory() as folder:
                client = QwenCliClient(folder=folder,device=device)
                args = []
                child = Mock()
                child.poll.return_value = 0
                child.returncode = 0
                def launch(value):
                    args.extend(value)
                    client.process = child
                with patch.object(client,"verify_files"),patch.object(client,"launch",side_effect=launch), \
                     patch("capri.audio.voice_service.decode",return_value=np.zeros(24000)), \
                     patch("capri.audio.clone_effects.process_layers",return_value=np.zeros(24000)), \
                     patch("capri.audio.voice_service.write_wav"):
                    client.render("Тест.",str(Path(folder)/"out.wav"),threading.Event())
                self.assertIn("--tts-speaker-file",args)
                self.assertEqual(args[args.index("--seed")+1],"42")
                self.assertEqual(args[args.index("-ngl")+1],"all" if device == "cuda" else "0")
                if device == "cuda":
                    self.assertEqual(args[args.index("-c")+1],"4096")
                    self.assertEqual(args[args.index("--device")+1],"CUDA0")
                    self.assertEqual(Path(args[0]).parent,Path(folder)/CUDA_FOLDER)
                else:
                    self.assertNotIn("--device",args)

    def test_cuda_probe_and_checksums_are_required_and_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root/CUDA_FOLDER
            runtime.mkdir()
            manifest = {}
            for name in ("llama-tts.exe","ggml-cuda.dll"):
                data = name.encode()
                (runtime/name).write_bytes(data)
                manifest[name] = hashlib.sha256(data).hexdigest()
            (root/"bundled").mkdir()
            (root/"bundled/qwen-tts-cuda-runtime.json").write_text(json.dumps(manifest))
            client = QwenCliClient(folder=root,device="cuda")
            with patch.object(QwenClient,"verify_files"),patch("capri.audio.qwen_cli_backend.RESOURCE_ROOT",root), \
                 patch("capri.audio.qwen_cli_backend.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout="CUDA0: NVIDIA",stderr="")) as probe:
                client.verify_files()
                client.verify_files()
                probe.assert_called_once()
                (runtime/"ggml-cuda.dll").write_bytes(b"corrupt")
                client._cuda_verified = False
                with self.assertRaisesRegex(ValueError,"checksum"):
                    client.verify_files()

    def test_missing_gpu_fails_before_synthesis(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root/CUDA_FOLDER
            runtime.mkdir()
            (runtime/"llama-tts.exe").touch()
            (root/"bundled").mkdir()
            (root/"bundled/qwen-tts-cuda-runtime.json").write_text("{}")
            client = QwenCliClient(folder=root,device="cuda")
            with patch.object(QwenClient,"verify_files"),patch("capri.audio.qwen_cli_backend.RESOURCE_ROOT",root), \
                 patch("capri.audio.qwen_cli_backend.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout="Available devices: (none)",stderr="")):
                with self.assertRaisesRegex(RuntimeError,"CUDA"):
                    client.verify_files()

    def test_cuda_installer_keeps_cpu_binary_models_and_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            voice = root/"voice"
            voice.mkdir()
            for name in ("llama-tts.exe","model.gguf","voice-reference.wav"):
                (voice/name).write_bytes(b"unchanged")
            archives = []
            for index,names in enumerate((("llama-tts.exe","ggml-cuda.dll"),("cublas64_12.dll","cudart64_12.dll"))):
                path = root/f"{index}.zip"
                with zipfile.ZipFile(path,"w") as bundle:
                    for name in names:
                        bundle.writestr("bin/"+name,name.encode())
                archives.append(path)
            def download(name,digest,cache):
                return archives[list(install_qwen_cuda.ASSETS).index(name)]
            with patch.object(install_qwen_cuda,"download",side_effect=download),patch.object(install_qwen_cuda,"RESOURCE_ROOT",root):
                install_qwen_cuda.install(voice,root/"cache")
            for name in ("llama-tts.exe","model.gguf","voice-reference.wav"):
                self.assertEqual((voice/name).read_bytes(),b"unchanged")
            self.assertTrue((voice/CUDA_FOLDER/"ggml-cuda.dll").is_file())
