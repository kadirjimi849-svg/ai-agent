"""One log function for the CLI, the autopilot and the dashboard (last lines kept in memory + data/bot.log)."""
import collections
import threading
import time
from pathlib import Path

LINES = collections.deque(maxlen=500)
_lock = threading.Lock()
_file: Path | None = None


def set_file(path):
    global _file
    _file = Path(path)


def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + " ".join(str(x) for x in a)
    with _lock:
        LINES.append(line)
        print(line, flush=True)
        if _file:
            try:
                with _file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass


def tail(n=200):
    with _lock:
        return list(LINES)[-n:]
