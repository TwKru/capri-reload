"""Generate one uncached phrase and measure elapsed time and total GPU memory."""
import argparse
import json
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np

from capri.audio.qwen_cli_backend import QwenCliClient
from capri.core.paths import PROJECT_ROOT


def gpu_memory():
    result = subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],
        capture_output=True,text=True,timeout=5,creationflags=0x08000000)
    return int(result.stdout.strip().splitlines()[0]) if result.returncode == 0 else None


def benchmark(device, text, output, warmup=False):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    client = QwenCliClient(device=device,context_size=4096)
    cancel,finished = threading.Event(),threading.Event()
    if warmup:
        client.warmup(cancel)
    samples = []
    baseline = gpu_memory()

    def monitor():
        while not finished.is_set():
            value = gpu_memory()
            if value is not None:
                samples.append(value)
            finished.wait(.25)

    monitor_thread = threading.Thread(target=monitor,daemon=True)
    monitor_thread.start()
    label = device+("-warm" if warmup else "")
    destination = output/(label+".wav")
    started = time.perf_counter()
    try:
        client.render(text,str(destination),cancel,volume=100)
    finally:
        elapsed = time.perf_counter()-started
        finished.set()
        monitor_thread.join(6)
        client.close()
        if (client.folder/"worker.log").exists():
            shutil.copy2(client.folder/"worker.log",output/(label+"-worker.log"))
    with wave.open(str(destination),"rb") as file:
        duration = file.getnframes()/file.getframerate()
        samples_pcm = np.frombuffer(file.readframes(file.getnframes()),dtype="<i2")
    if duration < .3 or not len(samples_pcm) or np.max(np.abs(samples_pcm.astype(np.int32))) < 10:
        raise ValueError("Synthesized audio is empty or silent")
    peak = max(samples) if samples else baseline
    result = {"device":device,"model":"Q8_0","warmup":warmup,"text":text,"elapsed_seconds":round(elapsed,3),
              "cuda_graphs":False if device == "cuda" else None,"context_size":client.context_size if device == "cuda" else None,
              "audio_seconds":round(duration,3),"real_time_factor":round(elapsed/duration,3),
              "gpu_baseline_mib":baseline,"gpu_total_peak_mib":peak,
              "gpu_incremental_peak_mib":peak-baseline if peak is not None and baseline is not None else None}
    (output/(label+".json")).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device",choices=("cpu","cuda"),required=True)
    parser.add_argument("--text",default="Проверяю скорость генерации голоса.")
    parser.add_argument("--output",type=Path,default=PROJECT_ROOT/"reports"/"gpu-voice"/"benchmark")
    parser.add_argument("--warmup",action="store_true",help="Exclude initial integrity checks and DSP imports, as after app startup")
    args = parser.parse_args()
    benchmark(args.device,args.text,args.output,args.warmup)
