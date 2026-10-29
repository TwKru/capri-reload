import asyncio
import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.request

import cancellation
import actions
import voice


class CancellationTests(unittest.TestCase):
    def test_index_wait_can_be_cancelled_before_eight_second_timeout(self):
        scope = cancellation.Scope()
        started, finished = threading.Event(), threading.Event()
        results = []
        def wait_index():
            try:
                with scope.bind():
                    started.set()
                    cancellation.wait_event(threading.Event(), 8)
            except cancellation.RequestCancelled:
                results.append("cancelled")
            finally:
                finished.set()
        worker = threading.Thread(target=wait_index, daemon=True)
        worker.start()
        self.assertTrue(started.wait(1))
        scope.cancel()
        self.assertTrue(finished.wait(1))
        worker.join(1)
        self.assertEqual(results, ["cancelled"])
        event = threading.Event()
        self.assertFalse(cancellation.wait_event(event, 0))
        event.set()
        self.assertTrue(cancellation.wait_event(event, 0))

    def test_stop_cancels_fallback_voice_synthesis_after_processing_failure(self):
        started, finished = threading.Event(), threading.Event()
        speaker = voice.Speaker({"tts_engine": "edge"})
        results = []
        async def save(path):
            if Path(path).name == "voice.mp3":
                started.set()
                await asyncio.sleep(10)
        with tempfile.TemporaryDirectory() as folder, patch("edge_tts.Communicate") as edge, \
                patch("voice.decode", side_effect=ValueError("bad audio")):
            edge.return_value.save = save
            def render():
                try:
                    speaker.render("Первая фраза. Вторая фраза.", str(Path(folder) / "voice.wav"))
                except cancellation.RequestCancelled:
                    results.append("cancelled")
                finally:
                    finished.set()
            worker = threading.Thread(target=render, daemon=True)
            worker.start()
            self.assertTrue(started.wait(2))
            speaker.stop()
            self.assertTrue(finished.wait(1))
            worker.join(1)
        self.assertEqual(results, ["cancelled"])

    def test_old_jobs_are_discarded_but_new_jobs_survive(self):
        epoch = [0]
        jobs = cancellation.JobQueue(lambda: epoch[0])
        jobs.put(("text", "old"))
        epoch[0] = 1
        jobs.put(("text", "new"))
        jobs.discard_before(1)
        self.assertEqual(jobs.get_nowait(), ("text", "new"))
        self.assertTrue(jobs.empty())
        jobs.task_done()
        self.assertEqual(jobs.unfinished_tasks, 0)

    def test_stop_releases_key_even_in_middle_of_chord(self):
        scope = cancellation.Scope()
        events = []
        def key(code, scan, flags, extra):
            events.append((code, flags))
            if not flags & 2:
                scope.cancel()
        with patch("actions.ctypes.windll.user32", Mock(keybd_event=key)), scope.bind():
            with self.assertRaises(cancellation.RequestCancelled):
                actions.send_keys(["ctrl", "a"])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][0], events[1][0])
        self.assertFalse(events[0][1] & 2)
        self.assertTrue(events[1][1] & 2)

    def test_cancelled_chain_never_runs_next_step(self):
        with patch("actions.AppIndex.build"):
            app = actions.Actions({}, ".", None)
        scope = cancellation.Scope()
        def first(step):
            scope.cancel()
            return actions.Reply("Готово.")
        app.handle_one = Mock(side_effect=first)
        with patch("automation.foreground_title", return_value=""), scope.bind():
            with self.assertRaises(cancellation.RequestCancelled):
                app.run_chain(["первая", "вторая"])
        app.handle_one.assert_called_once_with("первая")

    def test_stop_during_paste_restores_previous_clipboard(self):
        import automation
        scope = cancellation.Scope()
        def stop_on_paste(keys):
            scope.cancel()
        with patch("media._clipboard_text", return_value="old"), \
                patch("automation.set_clipboard", return_value=True) as clipboard, \
                patch("actions.send_keys", side_effect=stop_on_paste), scope.bind():
            with self.assertRaises(cancellation.RequestCancelled):
                automation.paste_text("new")
        self.assertEqual([call.args[0] for call in clipboard.call_args_list], ["new", "old"])

    def test_ollama_connection_is_closed_while_waiting_for_first_response(self):
        started, disconnected = threading.Event(), threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                started.set()
                self.connection.settimeout(2)
                if self.connection.recv(1) == b"":
                    disconnected.set()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        scope, results = cancellation.Scope(), []
        def request():
            try:
                with scope.bind():
                    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/chat",
                                                 data=json.dumps({"prompt": "test"}).encode())
                    with cancellation.open_url(req, timeout=10) as response:
                        response.read()
            except cancellation.RequestCancelled:
                results.append("cancelled")
        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        self.assertTrue(started.wait(2))
        scope.cancel()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, ["cancelled"])
        self.assertTrue(disconnected.wait(1))

    def test_stop_cancels_pending_voice_synthesis(self):
        started, finished = threading.Event(), threading.Event()
        speaker = voice.Speaker({"tts_engine": "edge"})
        async def save(path):
            started.set()
            await asyncio.sleep(10)
        results = []
        with tempfile.TemporaryDirectory() as folder, patch("edge_tts.Communicate") as edge:
            edge.return_value.save = save
            def render():
                try:
                    speaker.render("Длинный ответ.", str(Path(folder) / "voice.wav"))
                except cancellation.RequestCancelled:
                    results.append("cancelled")
                finally:
                    finished.set()
            worker = threading.Thread(target=render, daemon=True)
            worker.start()
            self.assertTrue(started.wait(2))
            speaker.stop()
            self.assertTrue(finished.wait(1))
            worker.join(1)
        self.assertEqual(results, ["cancelled"])
