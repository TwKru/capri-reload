"""Отмена операций, очереди и HTTP-запросов без принудительного завершения потоков."""
from contextlib import contextmanager
from contextvars import ContextVar
import http.client
import queue
import socket
import threading
import time
import urllib.parse
import urllib.request


class RequestCancelled(BaseException):
    """Управление потоком: не превращать остановку в ошибку команды."""


_current = ContextVar("capri_cancel_scope", default=None)


class Scope:
    def __init__(self, cancelled=lambda: False):
        self.predicate = cancelled
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.closers = set()

    def cancel(self):
        self.event.set()
        with self.lock:
            closers = list(self.closers)
        for close in closers:
            try:
                close()
            except (OSError, ValueError):
                pass

    def checkpoint(self):
        if self.event.is_set() or self.predicate():
            self.cancel()
            raise RequestCancelled()

    @contextmanager
    def bind(self):
        token = _current.set(self)
        try:
            self.checkpoint()
            yield self
        finally:
            _current.reset(token)

    @contextmanager
    def track(self, close):
        with self.lock:
            self.closers.add(close)
        try:
            self.checkpoint()
            yield
        finally:
            with self.lock:
                self.closers.discard(close)


@contextmanager
def cleanup():
    """Только короткое восстановление ресурсов: клавиши, буфер обмена."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def checkpoint():
    scope = _current.get()
    if scope:
        scope.checkpoint()


def wait(seconds):
    scope = _current.get()
    if scope is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        scope.checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        scope.event.wait(min(.05, remaining))


def wait_event(event, timeout):
    """Ожидать готовность фонового индекса, сохраняя немедленную отмену."""
    deadline = time.monotonic() + timeout
    while True:
        checkpoint()
        remaining = max(0.0, deadline - time.monotonic())
        ready = event.wait(min(.05, remaining))
        checkpoint()
        if ready:
            return True
        if remaining <= .05:
            return False


class Job(tuple):
    def __new__(cls, value, epoch):
        job = super().__new__(cls, value)
        job.epoch = epoch
        return job


class JobQueue(queue.Queue):
    def __init__(self, epoch):
        super().__init__()
        self.epoch = epoch

    def put(self, item, block=True, timeout=None):
        super().put(Job(item, self.epoch()), block, timeout)

    def discard_before(self, epoch):
        with self.mutex:
            kept = [job for job in self.queue if job.epoch >= epoch]
            removed = len(self.queue) - len(kept)
            self.queue.clear()
            self.queue.extend(kept)
            self.unfinished_tasks -= removed
            if self.unfinished_tasks == 0:
                self.all_tasks_done.notify_all()
            self.not_full.notify_all()


def _shutdown(sock):
    if sock:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


@contextmanager
def open_url(request, timeout):
    """Разорвать соединение с Ollama даже во время ожидания первых заголовков."""
    scope = _current.get()
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    parsed = urllib.parse.urlsplit(url)
    if scope and parsed.scheme == "http" and parsed.hostname == "127.0.0.1":
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
        try:
            scope.checkpoint()
            connection.connect()
            sock = connection.sock
            with scope.track(lambda: _shutdown(sock)):
                scope.checkpoint()
                path = parsed.path + ("?" + parsed.query if parsed.query else "")
                method = request.get_method() if isinstance(request, urllib.request.Request) else "GET"
                body = request.data if isinstance(request, urllib.request.Request) else None
                headers = dict(request.header_items()) if isinstance(request, urllib.request.Request) else {}
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                try:
                    scope.checkpoint()
                    if response.status >= 400:
                        raise OSError(f"HTTP {response.status}: {response.reason}")
                    yield response
                finally:
                    response.close()
        except Exception:
            scope.checkpoint()
            raise
        finally:
            connection.close()
    else:
        checkpoint()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if scope:
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                with scope.track(lambda: _shutdown(sock)):
                    yield response
            else:
                yield response
        checkpoint()
