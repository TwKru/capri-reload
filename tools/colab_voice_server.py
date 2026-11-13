"""Interactive Colab Qwen session: clean speech over an authenticated Gradio API."""
import hashlib
import secrets
import tempfile
import threading
import time
from pathlib import Path


def serve(reference, password, checkpoint=None):
    import gradio as gr
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    reference = Path(reference)
    if not reference.is_file() or len(password) < 12:
        raise ValueError("Нужны образец голоса и пароль длиной минимум 12 символов")
    model_path = str(checkpoint or "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = Qwen3TTSModel.from_pretrained(model_path, device_map="cuda:0", dtype=dtype,
                                         attn_implementation="sdpa")
    reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    model_hash = model_path + ":" + str(getattr(model.model.config, "_commit_hash", "unknown"))
    if checkpoint:
        with (Path(checkpoint) / "model.safetensors").open("rb") as file:
            model_hash = hashlib.file_digest(file, "sha256").hexdigest()
    identity = hashlib.sha256(f"colab-raw-v1:{reference_hash}:{model_hash}".encode()).hexdigest()
    prompt = None if checkpoint else model.create_voice_clone_prompt(
        ref_audio=str(reference), x_vector_only_mode=True)
    lock = threading.Lock()
    output_dir = Path(tempfile.mkdtemp(prefix="capri_speech_"))

    def synthesize(text):
        text = " ".join(str(text).split())
        if not text or len(text) > 300:
            raise gr.Error("Нужна фраза от 1 до 300 символов")
        with lock, torch.inference_mode():
            torch.cuda.synchronize()
            started = time.perf_counter()
            if checkpoint:
                wavs, rate = model.generate_custom_voice(text=text, speaker="capri", language="Russian")
            else:
                wavs, rate = model.generate_voice_clone(text=text, language="Russian", voice_clone_prompt=prompt)
            torch.cuda.synchronize()
            generated = time.perf_counter()
            path = output_dir / (secrets.token_hex(12) + ".wav")
            sf.write(str(path), wavs[0], rate, subtype="PCM_16")
            duration = len(wavs[0]) / rate
            return str(path), {"generation_seconds": generated - started,
                               "write_seconds": time.perf_counter() - generated,
                               "audio_seconds": duration,
                               "rtf": (generated - started) / max(duration, .001)}

    def speak(text):
        return synthesize(text)[0]

    with gr.Blocks(delete_cache=(600, 1800)) as demo:
        gr.Markdown("# Капри — голос Colab\nСинтез на GPU. Тон, ускорение и дубль добавляет приложение на ПК.")
        text = gr.Textbox(label="Реплика", value="Привет! Я Капри.")
        audio = gr.Audio(label="Проверить голос", type="filepath")
        gr.Button("Озвучить").click(speak, text, audio, api_name="speak", concurrency_limit=1)
        metadata = gr.JSON(visible=False)
        timing = gr.JSON(label="Время синтеза", visible=False)
        gr.Button(visible=False).click(synthesize, text, [audio, timing], api_name="speak_timed", concurrency_limit=1)
        gr.Button(visible=False).click(lambda: {"voice_id": identity, "processing": "raw", "features": ["timings"]},
                                       outputs=metadata, api_name="identity")
    demo.queue(max_size=8)
    demo.launch(share=True, auth=("capri", password), show_error=False,
                allowed_paths=[str(output_dir)], prevent_thread_lock=True)
    return demo
