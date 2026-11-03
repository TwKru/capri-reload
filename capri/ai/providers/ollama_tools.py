"""JSON и зрение Ollama через тот же локальный сервер, без облачного ключа."""
import json
import urllib.request

from capri.core import cancellation


class OllamaClient:
    def __init__(self, cfg):
        self.model = cfg.get("local_model", "qwen3:8b")
        self.timeout = max(10, float(cfg.get("local_timeout_seconds", 60)))

    def complete(self, messages, tokens=384, schema=None, images=None):
        rows = [dict(row) for row in messages]
        if images:
            rows[-1]["images"] = images
        payload = {"model": self.model, "messages": rows, "stream": False,
                   "think": False, "options": {"num_predict": tokens, "num_ctx": 8192}}
        if schema:
            payload["format"] = schema
        request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with cancellation.open_url(request, timeout=self.timeout) as response:
            data = json.load(response)
        cancellation.checkpoint()
        answer = data.get("message", {}).get("content", "").strip()
        if not answer:
            raise ValueError("Локальная модель не вернула ответ. Для экрана нужна модель со зрением.")
        return answer
