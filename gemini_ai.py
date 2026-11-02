"""Google AI Studio: Gemini generateContent REST, без Ollama и дополнительных SDK."""
import json
import logging
import os
import re
import urllib.error
import urllib.request

import cancellation
from openai_ai import APIError, OpenAI

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
log = logging.getLogger("capri")


class GeminiClient:
    def __init__(self, cfg):
        self.key = ((cfg.get("gemini_api_key") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip() or
                    os.environ.get("GOOGLE_API_KEY", "").strip())
        self.model = (cfg.get("gemini_model") or "").strip().removeprefix("models/") or DEFAULT_GEMINI_MODEL
        self.timeout = max(1, float(cfg.get("gemini_timeout_seconds", 30)))

    def _generation_config(self, tokens, schema):
        config = {"maxOutputTokens": tokens, "candidateCount": 1}
        if self.model.startswith("gemini-2.5"):
            budget = 128 if "-pro" in self.model else 0
            config["thinkingConfig"] = {"thinkingBudget": budget}
            config["maxOutputTokens"] += budget
        elif not self.model.startswith(("gemini-1.", "gemini-2.0")):
            minimal = self.model.startswith(("gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                                            "gemini-3.6-flash", "gemini-3-flash"))
            config["thinkingConfig"] = {"thinkingLevel": "MINIMAL" if minimal else "LOW"}
            # Gemini включает мысли в общий лимит вывода; оставляем место для ответа.
            config["maxOutputTokens"] += 256 if minimal else 512
        if schema is not None:
            config.update(responseMimeType="application/json", responseJsonSchema=schema)
        return config

    def complete(self, messages, tokens=800, schema=None):
        cancellation.checkpoint()
        if not self.key:
            raise APIError("Добавь ключ Google AI Studio в меню «Настройки → Нейросеть и API…».")
        if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", self.model):
            raise APIError("Укажи название модели Gemini, например " + DEFAULT_GEMINI_MODEL + ".")
        contents, instructions = [], []
        for message in messages:
            if message["role"] in ("system", "developer"):
                instructions.append(message["content"])
            else:
                role = "model" if message["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": message["content"]}]})
        payload = {"contents": contents, "generationConfig": self._generation_config(tokens, schema)}
        if instructions:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(instructions)}]}
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        try:
            with cancellation.open_url(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            errors = {400: "Google не принял запрос. Проверь ключ AI Studio и название модели.",
                      401: "Ключ Google AI Studio не подходит. Проверь его в настройках.",
                      403: "Нет доступа к Gemini API. Проверь ключ, доступ к модели и регион.",
                      404: "Модель Gemini не найдена. Проверь её название в настройках.",
                      429: "Лимит Gemini API исчерпан. Проверь квоту Google AI Studio и повтори позже."}
            raise APIError(errors.get(status, f"Ошибка Gemini API ({status}). Попробуй позже.")) from None
        except (OSError, ValueError):
            cancellation.checkpoint()
            raise APIError("Нет ответа от Google AI Studio. Проверь интернет и повтори запрос.") from None
        cancellation.checkpoint()
        if not isinstance(data, dict):
            raise APIError("Gemini вернула неверный ответ. Попробуй позже.")
        candidates = data.get("candidates") or []
        if not candidates:
            raise APIError("Gemini не смогла ответить на этот запрос. Попробуй переформулировать.")
        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason not in ("STOP", "MAX_TOKENS"):
            raise APIError("Gemini не завершила ответ на этот запрос. Попробуй переформулировать.")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str)
                         and not part.get("thought")).strip()
        if not text:
            raise APIError("Gemini вернула пустой ответ. Попробуй сократить запрос.")
        if reason == "MAX_TOKENS":
            if schema is not None:
                raise APIError("Gemini не завершила разбор команды. Попробуй сказать короче.")
            sentences = list(re.finditer(r'[.!?](?:[»”\"])?(?=\s|$)', text))
            text = text[:sentences[-1].end()] if sentences else text.rstrip() + "…"
        usage = data.get("usageMetadata") or {}
        log.info("Gemini токены: вход=%s, выход=%s, мысли=%s", usage.get("promptTokenCount", 0),
                 usage.get("candidatesTokenCount", 0), usage.get("thoughtsTokenCount", 0))
        return text


class Gemini(OpenAI):
    """Общие краткие реплики, история и память; транспорт обращается только к Google."""
    def __init__(self, cfg):
        self.client = GeminiClient(cfg)
        self.model = self.client.model
        self.history = []
        self.personality = None
        self.economy = bool(cfg.get("gemini_min_tokens", True))
