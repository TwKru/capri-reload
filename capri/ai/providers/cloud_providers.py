"""NVIDIA NIM, DeepSeek и Claude: общий интерфейс текста/JSON/изображений."""
import json
import logging
import os
import urllib.error
import urllib.request

from capri.ai.providers.openai_provider import APIError, OpenAI
from capri.core import cancellation

PROVIDERS = {
    "nvidia": {"label": "NVIDIA NIM", "model": "qwen/qwen3.5-122b-a10b", "url": "https://integrate.api.nvidia.com/v1/chat/completions", "env": "NVIDIA_API_KEY"},
    "deepseek": {"label": "DeepSeek", "model": "deepseek-flash", "url": "https://api.deepseek.com/chat/completions", "env": "DEEPSEEK_API_KEY"},
    "anthropic": {"label": "Claude / Anthropic", "model": "claude-opus-5-5", "url": "https://api.anthropic.com/v1/messages", "env": "ANTHROPIC_API_KEY"},
}
log = logging.getLogger("capri")


class CloudClient:
    def __init__(self, cfg):
        self.provider = cfg["ai_mode"]
        self.info = PROVIDERS[self.provider]
        self.model = cfg.get(f"{self.provider}_model") or (cfg.get("model") if self.provider == "anthropic" else None) or self.info["model"]
        self.key = (cfg.get(f"{self.provider}_api_key") or os.environ.get(self.info["env"], "")).strip()
        self.timeout = max(1, float(cfg.get(f"{self.provider}_timeout_seconds", 30)))

    def complete(self, messages, tokens=384, schema=None, images=None):
        cancellation.checkpoint()
        if not self.key:
            raise APIError(f"Добавь ключ {self.info['label']} в настройках нейросети.")
        messages = [dict(m) for m in messages]
        if schema is not None:
            messages.insert(0, {"role": "system", "content": "Верни только JSON по схеме: " + json.dumps(schema, ensure_ascii=False)})
        system = "\n".join(m["content"] for m in messages if m["role"] in ("system", "developer"))
        if self.provider == "anthropic":
            content = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
            if images:
                content[-1]["content"] = [{"type": "text", "text": content[-1]["content"]}] + [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}} for image in images]
            payload = {"model": self.model, "max_tokens": tokens, "system": system, "messages": content}
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        else:
            if images:
                messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}] + [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}} for image in images]
            payload = {"model": self.model, "messages": messages, "max_tokens": tokens, "stream": False}
            if self.provider == "deepseek":
                payload["thinking"] = {"type": "disabled"}
            if self.provider == "nvidia" and "qwen3.5" in self.model:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            if schema is not None and self.provider == "deepseek":
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": "Bearer " + self.key}
        request = urllib.request.Request(self.info["url"], data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers=dict(headers, **{"Content-Type": "application/json"}))
        try:
            with cancellation.open_url(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise APIError(f"{self.info['label']}: ошибка {status}. " +
                ("Проверь ключ и доступ к модели." if status in (400, 401, 403, 404) else "Проверь квоту или повтори позже.")) from None
        except (OSError, ValueError):
            cancellation.checkpoint()
            raise APIError(f"Не удалось получить ответ {self.info['label']}. Проверь интернет.") from None
        cancellation.checkpoint()
        if self.provider == "anthropic":
            text = "\n".join(p["text"] for p in data.get("content", []) if p.get("type") == "text")
            limited = data.get("stop_reason") == "max_tokens"
        else:
            choices = data.get("choices") or []
            text = choices[0].get("message", {}).get("content", "") if choices else ""
            limited = bool(choices and choices[0].get("finish_reason") == "length")
        if not isinstance(text, str) or not text.strip() or (limited and schema is not None):
            raise APIError(f"{self.info['label']} не вернула полный ответ. Уточни запрос.")
        log.info("%s usage: %s", self.provider, {key: value for key, value in (data.get("usage") or {}).items() if isinstance(value, int)})
        return text.strip()


class CloudAI(OpenAI):
    def __init__(self, cfg):
        self.client = CloudClient(cfg)
        self.model = self.client.model
        self.history = []
        self.personality = None
        self.economy = bool(cfg.get(f"{cfg['ai_mode']}_min_tokens", True))
