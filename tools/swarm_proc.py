"""Process-tree control for swarm agents: on Windows the venv python.exe is a launcher that starts the real
interpreter, so killing only the pid we launched can orphan the interpreter. Kill the whole tree we started."""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)  # launched with start_new_session, so pid is its group leader
        except OSError:
            pass


class TreeProc:
    """A Popen whose kill() takes down the launcher AND everything it started."""

    def __init__(self, cmd: list[str], port: int = 0, **kw):
        if os.name != "nt":
            kw.setdefault("start_new_session", True)
        self.proc, self.port = subprocess.Popen(cmd, **kw), port
        self.pid = self.proc.pid

    def poll(self):
        return self.proc.poll()

    def kill(self) -> None:
        kill_tree(self.pid)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


if __name__ == "__main__":  # test helper: spawn a grandchild, write its pid, then idle
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    open(sys.argv[1], "w").write(str(gc.pid))
    gc.wait()
