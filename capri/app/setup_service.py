"""Validate first-run choices and merge them without replacing existing user settings."""
import json
import os
import tempfile
from pathlib import Path

from capri.ai.providers.cloud_providers import PROVIDERS
from capri.ai.providers.gemini_provider import DEFAULT_GEMINI_MODEL
from capri.config.defaults import DEFAULTS

API_PROVIDERS = {
    "openai": {"label": "OpenAI", "model": DEFAULTS["openai_model"]},
    "gemini": {"label": "Google Gemini", "model": DEFAULT_GEMINI_MODEL},
    **PROVIDERS,
}


def api_settings(provider, key, model):
    if provider not in API_PROVIDERS or not key.strip() or not model.strip():
        raise ValueError("Выберите сервис, укажите ключ API и название модели.")
    return {"ai_mode": provider, "local_ai": False, "enable_ai": True, "intent_router": False,
            f"{provider}_api_key": key.strip(), f"{provider}_model": model.strip()}


def local_settings(files):
    if not all(Path(files.get(key, "")).is_file() for key in ("llama_executable", "llama_model")):
        raise ValueError("Не удалось подготовить локальную модель. Повторите загрузку.")
    return {**files, "ai_mode": "llamacpp", "local_ai": False, "enable_ai": True, "intent_router": False}


def save_setup(path, settings):
    path = Path(path)
    existing = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(existing, dict):
        raise ValueError("Файл настроек повреждён. Сохранение отменено.")
    if not path.exists() or existing.get("setup_pending"):
        existing.update(tts_engine="silero", silero_voice="baya", silero_pitch="medium", silero_speed=1.15,
                        voice_shift=.8, voice_fx=0, voice_glitch=.45, voice_lively=True)
    existing.update(settings, setup_complete=True, setup_pending=False, first_start_mainframe=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as output:
        temporary = Path(output.name)
        json.dump(existing, output, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
