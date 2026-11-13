"""Build a credential-free Colab bundle and an interactive training notebook."""
import argparse
import os
import zipfile
from pathlib import Path

from tools.voice_lab import AUDIO_EXTENSIONS, UPSTREAM_REVISION, prepare, write_json

ROOT = Path(__file__).resolve().parents[1]


def notebook():
    cells = []

    def markdown(text):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": text.splitlines(True)})

    def code(text):
        cells.append({"cell_type": "code", "metadata": {}, "source": text.splitlines(True),
                      "execution_count": None, "outputs": []})

    markdown("""# Капри: дообучение и библиотека реплик
Выберите **Среда выполнения → Сменить среду → GPU**. Выполняйте ячейки по очереди.
Это обучение Qwen3-TTS 0.6B на исходных весах, а не изменение локального Q8.
Записи, расшифровки, обученные веса и прогресс сохраняются в `MyDrive/CapriVoiceLab`.
Для полного обучения и сохранения optimizer желательно 25–30 ГБ свободного Drive.
GPU-среда ещё не проверена на ваших новых записях: при нехватке VRAM сократите длинные фрагменты.
Эффекты (тон +0,8, скорость +4,7%, дубль 1,5 мс) применит Капри при воспроизведении.
""")
    code('''from google.colab import drive
drive.mount('/content/drive')
from pathlib import Path
import os, sys, subprocess, json, zipfile
PROJECT = Path('/content/drive/MyDrive/CapriVoiceLab')
PROJECT.mkdir(parents=True, exist_ok=True)
os.environ['HF_HOME'] = str(PROJECT / 'hf-cache')
subprocess.run(['nvidia-smi'], check=True)
''')
    markdown("## Загрузить пакет\nВыберите `capri-voice-colab.zip`, созданный на компьютере командой `prepare_voice_colab.bat`. Достаточно загрузить один раз; после обрыва сессии пропустите эту ячейку, пакет остаётся на Drive.")
    code('''from google.colab import files
uploaded = files.upload()
for name, data in uploaded.items():
    if not name.endswith('.zip'):
        continue
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            target = (PROJECT / item.filename).resolve()
            if '\\\\' in item.filename or ':' in item.filename or not target.is_relative_to(PROJECT.resolve()):
                raise ValueError('Недопустимый путь в архиве')
            # Preserve edits for the same corpus; do not silently combine different corpora.
            if item.filename == 'corpus/corpus.json' and target.exists():
                current = json.loads(target.read_text(encoding='utf-8'))
                incoming = json.loads(archive.read(item).decode('utf-8'))
                if {r['sha256'] for r in current['recordings']} != {r['sha256'] for r in incoming['recordings']}:
                    raise ValueError('Другой корпус: выберите новую папку PROJECT для нового эксперимента')
                continue
            archive.extract(item, PROJECT)
print(PROJECT)
''')
    markdown("## Установка\nИсходники Qwen закреплены на проверенном коммите. Flash Attention не требуется: используется SDPA, для T4 выбран FP16, для новых GPU — BF16.")
    code(f'''UPSTREAM = Path('/content/Qwen3-TTS')
REVISION = '{UPSTREAM_REVISION}'
if not UPSTREAM.exists():
    subprocess.run(['git', 'clone', 'https://github.com/QwenLM/Qwen3-TTS.git', str(UPSTREAM)], check=True)
subprocess.run(['git', '-C', str(UPSTREAM), 'checkout', '--detach', REVISION], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-e', str(UPSTREAM),
                'faster-whisper==1.2.1', 'tensorboard'], check=True)
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(UPSTREAM))
import importlib
importlib.invalidate_caches()
from qwen_tts import Qwen3TTSModel
print('Qwen3-TTS import OK')
from voice_lab import training_manifest, transcribe
import torch
assert torch.cuda.is_available(), 'Нужна среда GPU'
print(torch.cuda.get_device_name(0))
''')
    markdown("## Расшифровки\nРядом с каждым исходником можно заранее положить `.txt` с точной репликой. Для остальных записей ячейка создаёт черновые расшифровки. Проверьте их на слух: музыка и речь других персонажей ухудшают обучение. Не включайте эффекты дубля в учебные записи, если доступны чистые оригиналы.")
    code('''CORPUS = PROJECT / 'corpus'
assert (CORPUS / 'corpus.json').exists(), 'Пакет пока без записей: добавьте voicenew на ПК и пересоберите пакет'
transcribe(CORPUS)
print((CORPUS / 'corpus.json').read_text(encoding='utf-8'))
''')
    markdown("Откройте `corpus/corpus.json` на Drive, исправьте `text`, прослушайте все записи, у проверенных выставьте `reviewed: true`. Если есть `issues`, исправьте исходник и соберите корпус заново. Ячейка ниже остановится, если записи не проверены. Не отмечайте ошибочную автоматическую расшифровку как правильную.")
    code('''RAW_JSONL = PROJECT / 'train_raw.jsonl'
print('Проверено записей:', training_manifest(CORPUS, RAW_JSONL))
''')
    markdown("## Аудиокоды\nИзвлекаются по одной записи, чтобы снизить расход памяти. При неизменном корпусе повторно не вычисляются.")
    code('''import hashlib
fingerprint = hashlib.sha256(RAW_JSONL.read_bytes()).hexdigest()
CODES = PROJECT / 'train_with_codes.jsonl'
STAMP = PROJECT / 'codes.sha256'
if not CODES.exists() or not STAMP.exists() or STAMP.read_text() != fingerprint:
    prepare_script = (UPSTREAM / 'finetuning/prepare_data.py').read_text()
    assert prepare_script.count('BATCH_INFER_NUM = 32') == 1
    patched = UPSTREAM / 'finetuning/capri_prepare_data.py'
    patched.write_text(prepare_script.replace('BATCH_INFER_NUM = 32', 'BATCH_INFER_NUM = 1'))
    temporary = CODES.with_suffix('.tmp.jsonl')
    subprocess.run([sys.executable, str(patched), '--device', 'cuda:0',
        '--tokenizer_model_path', 'Qwen/Qwen3-TTS-Tokenizer-12Hz',
        '--input_jsonl', str(RAW_JSONL), '--output_jsonl', str(temporary)], check=True)
    temporary.replace(CODES)
    STAMP.write_text(fingerprint)
print(CODES)
''')
    markdown("## Дообучение\nНачните с 3 эпох. Прогресс сохраняется после **полностью завершённой эпохи**, вместе с optimizer и RNG. После отключения заново выполните подключение Drive, установку и эту ячейку. Незавершённая эпоха повторится; флаг `latest.json` указывает только на полный снимок. Не меняйте корпус или параметры при продолжении: для нового эксперимента смените `RUN_NAME`.")
    code('''from huggingface_hub import snapshot_download
CODES = PROJECT / 'train_with_codes.jsonl'
assert CODES.exists(), 'Сначала подготовьте аудиокоды'
BASE = snapshot_download('Qwen/Qwen3-TTS-12Hz-0.6B-Base')
RUN_NAME = 'capri-new-v1'
RUN = PROJECT / 'runs' / RUN_NAME
EPOCHS = 3
subprocess.run([sys.executable, str(PROJECT / 'colab_train_voice.py'),
    '--upstream', str(UPSTREAM / 'finetuning'), '--state', str(RUN / 'state'),
    '--init_model_path', BASE, '--output_model_path', str(RUN / 'models'),
    '--train_jsonl', str(CODES), '--batch_size', '1', '--lr', '2e-6',
    '--num_epochs', str(EPOCHS), '--speaker_name', 'capri'], check=True)
''')
    markdown("## Проверка голоса и библиотека\nСначала генерируется пробная реплика. Библиотека экспортируется только после прослушивания и явного выбора `VOICE_OK = True`. Число эпох само по себе не гарантирует хорошего голоса. Все WAV в библиотеке чистые: эффекты добавляются на компьютере.")
    code('''from voice_lab import export_library
from IPython.display import Audio, display
CHECKPOINT = RUN / 'models' / f'checkpoint-epoch-{EPOCHS - 1}'
preview_phrases = PROJECT / 'preview-phrases.json'
preview_phrases.write_text(json.dumps(['Привет! Я Капри. Ну что, проверим новый голос?'], ensure_ascii=False))
export_library(CHECKPOINT, preview_phrases, PROJECT / 'preview')
preview_manifest = json.loads((PROJECT / 'preview/manifest.json').read_text())
display(Audio(filename=str(PROJECT / 'preview' / preview_manifest['entries'][0]['audio'])))
''')
    code('''VOICE_OK = False  # После прослушивания замените на True
assert VOICE_OK, 'Сначала прослушайте голос в предыдущей ячейке'
archive = export_library(CHECKPOINT, PROJECT / 'phrases.json', PROJECT / 'capri-library')
from google.colab import files
files.download(str(archive))
''')
    markdown("## Подключение на компьютере\nВ папке Капри выполните `py -m tools.install_voice_library ПУТЬ_К_capri-library.zip`, затем нажмите перезапуск. Совпавшие тексты берутся из библиотеки; новые ответы генерируются прежним локальным голосом. Обученные PyTorch-веса остаются на Drive и автоматически не заменяют Q8 GGUF. Colab не используется как постоянно включённый сервер. Сохранение состояния не отменяет его квоты и ограничения длительности сессий.")
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {"colab": {"name": "Capri_Voice_Lab.ipynb"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"}, "accelerator": "GPU"}, "cells": cells}


def build(source=ROOT / "voicenew", output=ROOT / "reports/voice-colab"):
    from capri.ai.persona.action_responses import ACTION_REPLIES
    from capri.ai.persona.system_prompts import LINES
    from capri.audio.voice_service import clean_for_speech
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    recordings = []
    if any(p.suffix.lower() in AUDIO_EXTENSIONS and p.relative_to(source).parts[0] != "emotions"
           for p in Path(source).rglob("*")):
        recordings = prepare(source, output / "corpus")

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from strings(item)

    phrases = ["Слушаю…", "Да?", "Я здесь."]
    phrases += [clean_for_speech(s) for s in strings([LINES, ACTION_REPLIES])
                if not any(c in s for c in "{}[]") and len(s) <= 160]
    phrases = list(dict.fromkeys(phrases))
    write_json(output / "phrases.json", phrases)
    write_json(output / "Capri_Voice_Lab.ipynb", notebook())
    remote = notebook()
    remote["cells"] = remote["cells"][:6]
    remote["metadata"]["colab"]["name"] = "Capri_Colab_Voice.ipynb"
    remote["cells"][0]["source"] = [
        "# Капри: генерация голоса на GPU Colab\n",
        "Включите GPU, подключите Drive, загрузите пакет и установите зависимости.\n",
        "Сохраняется основа Capri 2; тон +0,8, ускорение +4,7% и дубль 1,5 мс добавит Капри на ПК.\n",
        "PyTorch и GGUF могут звучать немного по-разному — сначала проверьте пробную фразу.\n",
        "Сессия временная. Ручной перезапуск не отменяет ограничения Colab.\n"]
    remote["cells"] += [
        {"cell_type": "markdown", "metadata": {}, "source": [
            "## Запустить голос\nЗадайте пароль (минимум 12 символов). Он не выводится и не отправляется в пакет.\n",
            "После запуска скопируйте ссылку `gradio.live`. На ПК откройте `connect_colab_voice.bat`,\n",
            "введите ссылку и этот пароль, затем перезапустите Капри.\n",
            "Для текущего Capri 2 оставьте CHECKPOINT=None; для дообученного голоса выберите папку checkpoint на Drive.\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "from getpass import getpass\n",
            "from colab_voice_server import serve\n",
            "CHECKPOINT = None\n",
            "password = getpass('Пароль голоса (минимум 12 символов): ')\n",
            "demo = serve(PROJECT / 'capri2-reference.wav', password, checkpoint=CHECKPOINT)\n",
            "print('Ссылка для Капри:', demo.share_url)\n"]},
        {"cell_type": "markdown", "metadata": {}, "source": [
            "## После отключения\nПодключите Drive и заново выполните установку и запуск.\n",
            "Пакет загружать повторно не нужно. Введите новую ссылку в `connect_colab_voice.bat`.\n",
            "Локальный кэш сохранится; хихиканье и другие записи эмоций воспроизводятся на ПК.\n",
            "Во время отсутствия сессии новые реплики Colab недоступны. Для возврата локального голоса\n",
            "в config.json задайте tts_engine=qwen_clone и перезапустите Капри.\n",
            "[Условия и ограничения Colab](https://research.google.com/colaboratory/faq.html):\n",
            "доступность GPU и время сессии не гарантированы, бесплатные сессии могут завершаться при работе через внешнее приложение.\n"]},
    ]
    write_json(output / "Capri_Colab_Voice.ipynb", remote)
    archive = output / "capri-voice-colab.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("voice_lab.py", "colab_train_voice.py", "colab_voice_server.py"):
            bundle.write(ROOT / "tools" / name, name)
        reference = Path(os.environ.get("LOCALAPPDATA", "")) / "Capri/voice/qwen3-b12069/presets/capri2/voice-reference.wav"
        if reference.is_file():
            bundle.write(reference, "capri2-reference.wav")
        else:
            print("Не найден образец Capri 2: поместите capri2-reference.wav в папку CapriVoiceLab на Drive.")
        bundle.write(output / "phrases.json", "phrases.json")
        if recordings:
            bundle.write(output / "corpus/corpus.json", "corpus/corpus.json")
            for record in recordings:
                bundle.write(output / "corpus" / record["audio"], "corpus/" + record["audio"])
    print(f"Пакет: {archive}\nЗаписей: {len(recordings)}; готовых текстов: {len(phrases)}")
    if not recordings:
        print("Обучение ещё невозможно: добавьте записи в voicenew и повторите запуск.")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "voicenew")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/voice-colab")
    args = parser.parse_args()
    build(args.source, args.output)
