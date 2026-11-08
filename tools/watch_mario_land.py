"""Super Mario Land: players search headless underneath, and the viewer shows only the best run.

Run from the repo root:  uv run python tools/watch_mario_land.py [--workers 2] [--minutes 90]

Each worker is a headless emulator process (mario_search). It keeps a save state per stretch reached, tries button
patterns from the furthest ones, and publishes its best input sequence to runs/mario-land/best-<n>.json. Distance
decides what is best; style value (mario_value) breaks ties. The display process (mario_display) owns the only
viewer card and replays the best sequence. This file only wires the processes together.
"""
import argparse
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

from mario_search import DIR, INBOX, MACROS, clear_best, find_rom, low_priority, worker_main
from mario_display import AGENT, Display


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=90)
    a = ap.parse_args()
    rom_path = find_rom()
    low_priority()
    DIR.mkdir(parents=True, exist_ok=True)
    clear_best()
    INBOX.mkdir(parents=True, exist_ok=True)
    end = time.time() + a.minutes * 60
    from mario_maps import cartographer_main
    procs = [mp.Process(target=worker_main, args=(i, end, rom_path), daemon=True) for i in range(a.workers)]
    procs.append(mp.Process(target=cartographer_main, args=(end, MACROS, rom_path), daemon=True))
    for p in procs:
        p.start()
    from pokeagent import agent_registry
    from pokeagent.control_server import ControlServer
    root = Path(".")
    d = ctl = None
    registered = False
    try:
        d = Display(a.workers, rom_path)
        ctl = ControlServer(lambda: d.snap, {})
        port = ctl.start()
        agent_registry.register(root, AGENT, "explorer", port, d.pub.name, token=ctl.token)
        registered = True
        print(f"registered {AGENT} on port {port}, slot {d.pub.name}, pid {os.getpid()}", flush=True)
        while time.time() < end:
            d.play_best()
    finally:
        if registered:
            agent_registry.unregister(root, AGENT)
        if ctl is not None:
            ctl.stop()
        if d is not None:
            d.pub.close()
            d.emu.close()
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
