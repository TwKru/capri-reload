"""Adapt the pinned official Qwen trainer for SDPA, T4 and epoch-boundary resume."""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

if __package__:
    from tools.voice_lab import UPSTREAM_REVISION
else:
    from voice_lab import UPSTREAM_REVISION


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Версия официального тренера отличается от проверенной: " + old[:70])
    return source.replace(old, new, 1)


def adapt(source):
    source = replace_once(source, 'mixed_precision="bf16"', 'mixed_precision=capri_precision')
    source = replace_once(source, 'torch_dtype=torch.bfloat16,', 'torch_dtype=torch.float32,')
    source = replace_once(source, 'attn_implementation="flash_attention_2",', 'attn_implementation="sdpa",')
    source = replace_once(source, '    config = AutoConfig.from_pretrained(MODEL_PATH)',
                          '    qwen3tts.model.talker.gradient_checkpointing_enable()\n'
                          '    qwen3tts.model.talker.config.use_cache = False\n'
                          '    config = AutoConfig.from_pretrained(MODEL_PATH)')
    source = replace_once(source, '    num_epochs = args.num_epochs',
                          '    start_epoch, target_speaker_embedding = capri_restore(accelerator, args)\n'
                          '    num_epochs = args.num_epochs')
    source = replace_once(source, '    for epoch in range(num_epochs):',
                          '    for epoch in range(start_epoch, num_epochs):')
    source = replace_once(source, '            with accelerator.accumulate(model):',
                          '            with accelerator.accumulate(model), accelerator.autocast():')
    source = replace_once(source, '            save_file(state_dict, save_path)',
                          '            save_file(state_dict, save_path)\n'
                          '        capri_save(accelerator, args, epoch, target_speaker_embedding)')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    options, remaining = parser.parse_known_args()
    import torch
    from accelerate.utils import set_seed
    set_seed(42)
    if not torch.cuda.is_available():
        raise RuntimeError("Выберите GPU в настройках среды Colab")
    precision = "bf16" if torch.cuda.is_bf16_supported() else "fp16"
    options.state.mkdir(parents=True, exist_ok=True)

    def signature(args):
        return {"dataset": hashlib.sha256(Path(args.train_jsonl).read_bytes()).hexdigest(),
                "revision": UPSTREAM_REVISION, "base": args.init_model_path,
                "batch_size": args.batch_size, "lr": args.lr, "speaker": args.speaker_name,
                "precision": precision}

    def restore(accelerator, args):
        pointer = options.state / "latest.json"
        if not pointer.exists():
            return 0, None
        metadata = json.loads(pointer.read_text())
        if metadata["signature"] != signature(args):
            raise ValueError("Датасет или параметры изменились. Используйте новую папку state для нового обучения.")
        state = options.state / metadata["directory"]
        if not (state / "complete.json").exists():
            raise RuntimeError("Состояние не было полностью сохранено")
        accelerator.load_state(str(state))
        embedding = torch.load(state / "speaker.pt", map_location=accelerator.device, weights_only=True)
        print(f"Продолжаем с эпохи {metadata['next_epoch'] + 1}; optimizer и RNG восстановлены")
        return metadata["next_epoch"], embedding

    def save(accelerator, args, epoch, embedding):
        if not accelerator.is_main_process:
            return
        name = f"epoch-{epoch:04d}"
        target = options.state / name
        target.mkdir(exist_ok=True)
        accelerator.save_state(str(target))
        torch.save(embedding.detach().cpu(), target / "speaker.pt")
        metadata = {"directory": name, "next_epoch": epoch + 1, "signature": signature(args)}
        (target / "complete.json").write_text(json.dumps(metadata), encoding="utf-8")
        temporary = options.state / "latest.tmp.json"
        temporary.write_text(json.dumps(metadata), encoding="utf-8")
        os.replace(temporary, options.state / "latest.json")
        # After the new snapshot is complete, retain only the latest optimizer state.
        for old in options.state.glob("epoch-*"):
            if old != target and old.is_dir() and old.resolve().parent == options.state.resolve():
                shutil.rmtree(old)
        print(f"Эпоха {epoch + 1}: веса и полное состояние сохранены на Drive")

    source = adapt((options.upstream / "sft_12hz.py").read_text(encoding="utf-8"))
    compile(source, "capri_sft_12hz.py", "exec")
    sys.path.insert(0, str(options.upstream.resolve()))
    sys.argv = ["capri_sft_12hz.py", *remaining]
    namespace = {"__name__": "__main__", "__file__": str(options.upstream / "sft_12hz.py"),
                 "capri_precision": precision, "capri_restore": restore, "capri_save": save}
    exec(source, namespace)


if __name__ == "__main__":
    main()
