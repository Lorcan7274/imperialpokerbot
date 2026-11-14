import json
import os
import queue
import subprocess
import sys
import threading
import time

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")


class ProcSeat:
    """A bot file in its own isolated interpreter, timed from the dealer's side."""

    def __init__(self, path, python=sys.executable, timeout_ms=10.0, bank_ms=10000.0, setup=5.0,
                 timing=False):
        self.path = os.path.abspath(path)
        self.python = python
        self.timeout = timeout_ms / 1000.0
        self.bank = bank_ms / 1000.0
        self.setup = setup
        self.proc = None
        self.dead = False
        self.next_id = 0
        self.spent = []
        self.timeouts = 0
        self.errors = []
        self.bank_out = 0
        self.timing = timing
        self.detail = []
        self.load_s = None
        self.ready_s = None

    def spawn(self):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1"}
        self.proc = subprocess.Popen([self.python, "-I", RUNNER, self.path] + ["timing"] * self.timing, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=os.path.dirname(self.path), env=env)
        self.lines = queue.Queue()
        self.outbox = queue.Queue(maxsize=2000)
        threading.Thread(target=self.reader, daemon=True).start()
        threading.Thread(target=self.writer, daemon=True).start()

    def reader(self):
        while True:
            line = self.proc.stdout.readline(65537)
            if not line:
                break
            self.lines.put(line)
        self.lines.put(None)

    def writer(self):
        while True:
            data = self.outbox.get()
            if data is None:
                break
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                self.dead = True
                break

    def send(self, obj):
        if self.dead:
            return False
        self.outbox.put_nowait((json.dumps(obj) + "\n").encode())
        return True

    def wait(self, want, deadline):
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
                self.dead = True
                return None
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("type") == "load_error":
                return msg
            if msg.get("id") == want or (want is None and msg.get("type") == "loaded"):
                return msg

    def start_table(self, seat, info):
        t = time.perf_counter()
        self.spawn()
        msg = self.wait(None, t + self.setup)
        self.load_s = time.perf_counter() - t
        if msg is None or msg.get("type") != "loaded":
            self.dead = True
            self.errors.append((msg or {}).get("error") or "did not load")
            return
        self.next_id += 1
        t = time.perf_counter()
        self.send({"id": self.next_id, "type": "new_table", "info": info})
        msg = self.wait(self.next_id, t + self.setup)
        self.ready_s = time.perf_counter() - t
        if msg is None or msg.get("type") != "ready":
            self.dead = True
            self.errors.append((msg or {}).get("error") or "Agent() did not start")

    def act(self, state):
        if self.dead:
            return None
        if self.bank <= 0:
            self.bank_out += 1
            return None
        limit = min(self.timeout, self.bank)
        self.next_id += 1
        t = time.perf_counter()
        if not self.send({"id": self.next_id, "type": "act", "state": state}):
            return None
        msg = self.wait(self.next_id, t + limit)
        spent = time.perf_counter() - t
        self.bank -= min(spent, limit)
        self.spent.append(spent)
        if msg is None:
            if not self.dead:
                self.timeouts += 1
            return None
        if msg.get("type") == "error":
            self.errors.append(msg.get("error"))
            return None
        if self.timing:
            self.detail.append((spent, msg.get("parse", 0.0), msg.get("think", 0.0),
                                len(state["history"])))
        return msg

    def hand_end(self, summary):
        self.send({"type": "hand_end", "summary": summary})

    def close(self):
        if self.proc is None:
            return
        self.send({"type": "quit"})
        self.outbox.put_nowait(None)
        try:
            self.proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
