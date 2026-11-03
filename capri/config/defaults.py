"""Стандартные настройки; личные значения находятся в config.json."""
from capri.ai.providers.gemini_provider import DEFAULT_GEMINI_MODEL

DEFAULTS = {
    "ai_mode": "local",
    "openai_api_key": "",
    "openai_model": "gpt-6-luna",
    "openai_timeout_seconds": 30,
    "openai_min_tokens": True,
    "gemini_api_key": "",
    "gemini_model": DEFAULT_GEMINI_MODEL,
    "gemini_timeout_seconds": 30,
    "gemini_min_tokens": True,
    "enable_ai": False,
    "local_ai": True,
    "use_light_model_in_games": True,
    "game_chat_model": "qwen3:1.7b",
    "game_executables": [],
    "local_model": "qwen3:8b",
    "local_keep_alive": "30m",
    "local_timeout_seconds": 15,
    "intent_router": True,
    "router_model": "qwen3:0.6b",
    "router_timeout_seconds": 4.0,
    "router_num_gpu": 0,
    "web_app_lookup": True,
    "personality": True,
    "barge_in": True,
    "mic_device": None,
    "chatter": True,
    "chatter_min_minutes": 15,
    "chatter_max_minutes": 40,
    "roam_chance": 0.5,
    "teleport_on_answer": True,
    "search_when_unsure": True,
    "voice_volume": 100,     # громкость голоса Капри 0..100 (общая громкость Windows не меняется)
    "mic_gain": 1.0,         # громкость микрофона для Капри: 1 — как есть, 2 — вдвое громче
    "mic_sensitivity": 100,  # 100 — слышит всё; меньше — тихий шум и фон отбрасываются
    "user_name_mode": "none",  # как называть пользователя: "custom" — user_name, "windows" — имя пользователя
                               # Windows, "pc" — имя компьютера, "none" — не называть
    "user_name": "",
    "user_gender": "male",     # "male" / "female" — в каком роде Капри к тебе обращается
    "browser": "",
    "replies": {},           # свои ответы: {"фраза": "что ответит Капри"} — проверяются раньше команд и нейросети  # в каком браузере открывать сайты: "хром", "яндекс", "опера"… или путь к exe; "" — как в Windows
    "anthropic_api_key": "",
    "model": "claude-opus-5-5",
    "wake_words": ["капри", "каприз", "капре", "кепри", "капли"],
    "speak_wake_ack": False,
    "use_google_stt": True,
    "voice": "ru-RU-SvetlanaNeural",
    "tts_engine": "silero",
    "qwen_threads": 6,
    "silero_voice": "baya",
    "silero_pitch": "medium",
    "silero_speed": .92,
    "kokoro_voice": "masha",
    "kokoro_speed": 1.0,
    "kokoro_threads": 2,
    "tts_timeout_seconds": 8,
    "voice_rate": "+10%",
    "voice_pitch": "+20Hz",
    "voice_shift": .5,
    "voice_lively": True,
    "voice_fx": .12,
    "voice_glitch": 0,
    "listen_window_seconds": 8,
    "phrase_pause_seconds": 0.9,  # ожидание продолжения после короткой паузы, выделенной Vosk
    "followup_seconds": 0,
    "hide_after_seconds": 12,
    "greet_on_start": True,
    "vosk_model": "models/vosk-model-small-ru-0.22",
    "sites": {
        "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
        "гугл": "https://www.google.com", "google": "https://www.google.com",
        "яндекс": "https://ya.ru", "вк": "https://vk.com", "вконтакте": "https://vk.com",
        "почту": "https://mail.google.com", "почта": "https://mail.google.com",
        "гитхаб": "https://github.com", "твич": "https://www.twitch.tv",
        "википедию": "https://ru.wikipedia.org", "википедия": "https://ru.wikipedia.org",
        "переводчик": "https://translate.google.com", "карты": "https://yandex.ru/maps",
        "погоду": "https://yandex.ru/pogoda", "chatgpt": "https://chatgpt.com",
        "клод": "https://claude.ai", "кинопоиск": "https://www.kinopoisk.ru",
        "авито": "https://www.avito.ru", "озон": "https://www.ozon.ru",
        "вайлдберриз": "https://www.wildberries.ru"
    },
    "apps": {
        "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer",
        "диспетчер задач": "taskmgr", "параметры": "ms-settings:", "настройки": "ms-settings:",
        "панель управления": "control", "командную строку": "cmd", "командная строка": "cmd",
        "терминал": "wt", "пейнт": "mspaint", "paint": "mspaint", "ворд": "winword",
        "эксель": "excel", "браузер": "https://www.google.com",
        "настройки звука": "ms-settings:sound", "настройки экрана": "ms-settings:display",
        "корзину": "shell:RecycleBinFolder", "загрузки": "shell:Downloads"
    },
    "app_aliases": {
        "хром": "chrome", "гугл хром": "google chrome", "стим": "steam", "дискорд": "discord",
        "телеграм": "telegram", "телеграмм": "telegram", "спотифай": "spotify",
        "опера": "opera", "яндекс браузер": "yandex", "вс код": "visual studio code",
        "визуал студио код": "visual studio code", "обс": "obs", "эпик геймс": "epic games",
        "ватсап": "whatsapp", "зум": "zoom", "фотошоп": "photoshop", "майнкрафт": "minecraft"
    }
}
