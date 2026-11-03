"""Дополнительное распознавание речи; синтез голоса не затрагивается."""
import base64
import json
import os
import subprocess
import time
from pathlib import Path


class ParakeetRecognizer:
    """Адаптер офлайн Sherpa-ONNX с завершением фразы по тишине."""
    def __init__(self,folder,engine=None):
        if engine is None:
            try:
                import sherpa_onnx
            except ImportError:
                raise ValueError("Для Parakeet установи sherpa-onnx или выбери Vosk/Windows в MAINFRAME.") from None
            root = Path(folder)
            def find(pattern):
                paths = sorted(root.glob(pattern),key=lambda path:("int8" not in path.name,len(path.name)))
                if not paths:
                    raise ValueError("В папке Parakeet не найден " + pattern)
                return str(paths[0])
            engine = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=find("encoder*.onnx"),decoder=find("decoder*.onnx"),joiner=find("joiner*.onnx"),
                tokens=find("tokens.txt"),model_type="nemo_transducer",num_threads=2,
                sample_rate=16000,feature_dim=80,decoding_method="greedy_search",provider="cpu")
        self.engine = engine
        self.Reset()

    def Reset(self):
        self.buffer = bytearray()
        self.silence, self.active, self.result = 0., False, ""

    def AcceptWaveform(self,data):
        import numpy as np
        samples = np.frombuffer(data,dtype=np.int16).astype(np.float32)/32768.
        loud = float(np.sqrt(np.mean(samples*samples))) > .008 if len(samples) else False
        if loud:
            self.active, self.silence = True, 0.
        elif self.active:
            self.silence += len(samples)/16000.
        self.buffer += data
        if not self.active:
            del self.buffer[:-6400]
            return False
        if self.silence < .65 and len(self.buffer) < 16000*2*20:
            return False
        stream = self.engine.create_stream()
        stream.accept_waveform(16000,np.frombuffer(self.buffer,dtype=np.int16).astype(np.float32)/32768.)
        self.engine.decode_stream(stream)
        result = stream.result.text
        self.Reset()
        self.result = result
        return True

    def Result(self):
        return json.dumps({"text":self.result},ensure_ascii=False)

    def PartialResult(self):
        return '{"partial":""}'


WINDOWS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
$selected = $installed | Where-Object { $_.Culture.Name -eq 'ru-RU' } | Select-Object -First 1
if (!$selected) { $selected = $installed | Select-Object -First 1 }
if (!$selected) { throw 'No installed Windows speech recognizer' }
$recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($selected)
$recognizer.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
$recognizer.SetInputToDefaultAudioDevice()
try {
    while ($true) {
        $result = $recognizer.Recognize([TimeSpan]::FromSeconds(1))
        if ($result -and $result.Confidence -ge 0.35) {
            [Console]::WriteLine((@{text=$result.Text} | ConvertTo-Json -Compress))
        }
    }
} finally { $recognizer.Dispose() }
'''


def listen_windows(listener):
    if os.name != "nt":
        raise ValueError("Распознавание Windows доступно только в Windows")
    encoded = base64.b64encode(WINDOWS_SCRIPT.encode("utf-16-le")).decode("ascii")
    while True:
        listener.switch.clear()
        process = subprocess.Popen(["powershell.exe","-NoProfile","-NonInteractive","-EncodedCommand",encoded],
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",creationflags=0x08000000)
        listener.active_name = "Windows · системный микрофон"
        # При смене устройства/паузы старые результаты не переносятся в новую сессию.
        import threading
        session_done = threading.Event()
        def monitor(session_done=session_done, process=process):
            while not session_done.wait(.1):
                if listener.switch.is_set() or listener.muted.is_set():
                    process.terminate()
                    return
        threading.Thread(target=monitor,daemon=True).start()
        try:
            for line in process.stdout:
                if listener.muted.is_set() or listener.reset_req.is_set():
                    listener.reset_req.clear()
                    continue
                text = json.loads(line).get("text","").strip()
                if text:
                    listener.on_partial(text)
                    listener.on_final(text,b"")
            process.wait()
        finally:
            session_done.set()
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
        if process.returncode and not listener.muted.is_set() and not listener.switch.is_set():
            raise ValueError("Windows Speech недоступен. Установи речевой пакет Windows или выбери Vosk.")
        while listener.muted.is_set():
            time.sleep(.1)
