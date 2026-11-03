"""Постоянная очередь заданий, расписание и журнал шагов агента."""
import math
import sqlite3
import threading
import time


class JobStore:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                due REAL NOT NULL, repeat REAL NOT NULL DEFAULT 0, max_steps INTEGER NOT NULL, seconds INTEGER NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0, observations TEXT NOT NULL DEFAULT '[]', result TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job INTEGER NOT NULL, at REAL NOT NULL, text TEXT NOT NULL);
        """)
        self.connection.execute("UPDATE jobs SET status='paused',result='Приложение закрылось. Можно продолжить.' WHERE status IN ('running','queued')")
        self.connection.commit()

    def create(self, request, due=None, repeat=0, max_steps=60, seconds=3600):
        request = request.strip()
        if not request or len(request) > 6000:
            raise ValueError("Опиши задачу (до 6000 символов).")
        if not 1 <= int(max_steps) <= 500 or not 15 <= int(seconds) <= 43200 or not 0 <= repeat <= 604800:
            raise ValueError("Неверные ограничения задания.")
        with self.lock, self.connection:
            cursor = self.connection.execute("INSERT INTO jobs(request,status,due,repeat,max_steps,seconds,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                (request,"scheduled",due if due is not None else time.time(),repeat,max_steps,seconds,time.time(),time.time()))
            return cursor.lastrowid

    def get(self, ident):
        with self.lock:
            row = self.connection.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise ValueError("Задание не найдено")
            return dict(row)

    def list(self):
        with self.lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 200")]

    def claim_due(self, now=None):
        with self.lock, self.connection:
            rows = self.connection.execute("SELECT id FROM jobs WHERE status='scheduled' AND due<=? ORDER BY due LIMIT 1",
                                           (now if now is not None else time.time(),)).fetchall()
            ids = [row[0] for row in rows]
            for ident in ids:
                self.connection.execute("UPDATE jobs SET status='queued',updated=? WHERE id=?", (time.time(),ident))
            return ids

    def update(self, ident, **fields):
        if not set(fields) <= {"status","due","progress","observations","result","max_steps","seconds"}:
            raise ValueError("Неверные поля задания")
        fields["updated"] = time.time()
        with self.lock, self.connection:
            self.connection.execute("UPDATE jobs SET "+",".join(key+"=?" for key in fields)+" WHERE id=?", (*fields.values(),ident))

    def event(self, ident, text):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO events(job,at,text) VALUES(?,?,?)", (ident,time.time(),str(text)[:2000]))
            self.connection.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)")

    def log(self, ident):
        with self.lock:
            return [dict(row) for row in self.connection.execute("SELECT at,text FROM events WHERE job=? ORDER BY id DESC LIMIT 200", (ident,))][::-1]

    def resume(self, ident):
        row = self.get(ident)
        if row["status"] not in ("paused","failed","awaiting_confirmation"):
            raise ValueError("Это задание нельзя продолжить")
        if row["progress"] >= row["max_steps"]:
            self.update(ident, max_steps=min(500, row["max_steps"]+60))
            if row["progress"] >= 500:
                raise ValueError("Достигнут предел 500 шагов; создай новое задание.")
        self.update(ident, status="scheduled", due=max(time.time(),row["due"]), result="")

    def complete(self, ident, result):
        row = self.get(ident)
        if row["repeat"]:
            next_due = row["due"]+max(1,math.floor((time.time()-row["due"])/row["repeat"])+1)*row["repeat"]
            self.update(ident,status="scheduled",due=next_due,
                        progress=0,observations="[]",result=result)
        else:
            self.update(ident,status="done",result=result)

    def pause_all(self):
        with self.lock, self.connection:
            self.connection.execute("UPDATE jobs SET status='paused',updated=? WHERE status IN ('running','queued')", (time.time(),))

    def close(self):
        self.connection.close()
