"""Live swarm viewer: one window, every running agent's screen + status tiled.

    uv run python tools/watch.py                      # auto-detect: 8765 and 8800-8815
    uv run python tools/watch.py --ports 8800-8807 --fps 8

Frames come from each agent's pokeagent_frames_<port> shared-memory slot
(pokeagent.telemetry.FrameSubscriber) when the agent runs --frame-share, or
HTTP /screenshot.png + /status otherwise. Tiles auto-fit the window; click a
tile to focus, click/Esc/right-click to go back. No new dependencies.
"""
from __future__ import annotations

import argparse
import ctypes
import io
import json
import math
import threading
import time
import urllib.request

from pokeagent.goals import GOALS
from pathlib import Path
from typing import Optional

from PIL import Image

from pokeagent.telemetry import FrameSubscriber

BG = "#101010"
FG = "#d8d8d8"
DIM = "#777777"
BORDER = {"ok": "#3a3a3a", "battle": "#c0392b", "paused": "#b7950b", "dead": "#1d1d1d"}
TILE_H = 160 + 20


def fetch(port: int, path: str, timeout: float = 1.0) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


class Agent:
    def __init__(self, port: int) -> None:
        self.port = port
        self.png: Optional[bytes] = None  # latest frame: PNG bytes or raw RGB (see .raw)
        self.dims = (160, 144)            # frame WxH (half-res publishers send 80x72)
        self.raw = False                  # True when .png holds raw RGB from shared memory
        self.status: dict = {}
        self.ok = False
        self.fails = 0        # consecutive failed polls; a tile only goes offline after several
        self.seq = 0          # bumped every time a new frame lands (live-update signal)
        self.photo = None     # keep PhotoImage alive
        self.sub = FrameSubscriber(port, root=Path(__file__).resolve().parents[1])  # frame slot reader; attaches when the agent publishes


def poll(agent: Agent, hz: float, stop: threading.Event) -> None:
    period = 1.0 / hz
    n = 0
    while not stop.is_set():
        t0 = time.time()
        n += 1
        got_any = False
        res = agent.sub.read()
        if res is not None:
            agent.png, w, h = res
            agent.dims = (w, h)
            agent.raw = True
            agent.seq = agent.sub.seq
            got_any = True
        if not agent.sub.attached:  # no frame slot: fall back to HTTP screenshots
            png = fetch(agent.port, "/screenshot.png")
            if png is not None:
                agent.png = png
                agent.raw = False
                agent.seq += 1
                got_any = True
        if not agent.status or n % 4 == 0:  # status changes slowly; ~4Hz is plenty
            raw = fetch(agent.port, "/status")
            st = json.loads(raw) if raw else None
            if st is None:  # RL learners have no HTTP API; they write runs/rlstatus_<port>.json instead
                try:
                    st = json.loads(open(f"runs/rlstatus_{agent.port}.json").read())
                    st["_rl"] = True
                except Exception:
                    st = None
            if st is not None:
                agent.status = st
                got_any = True
        agent.fails = 0 if got_any else agent.fails + 1
        agent.ok = agent.fails < 4   # transient slow polls don't take a tile offline
        time.sleep(max(0.02, period - (time.time() - t0)))


_BRAIN_CACHE: dict = {}  # path -> (mtime, table, n_actions)


def _brain(a: Agent) -> str:
    """Model's-eye line for RL seats: latest trace obs + preferred action."""
    try:
        import glob
        from pokeagent.qdecode import brain_line
        from pokeagent.qmodels import load_model
        traces = sorted(glob.glob(f"runs/traces/*_{a.port}.jsonl"),
                        key=lambda p: Path(p).stat().st_mtime)
        if not traces:
            return ''
        last = Path(traces[-1]).read_text().strip().splitlines()[-1]
        rec = json.loads(last)
        obs = tuple(rec.get('final_obs') or (rec.get('path') or [[None]])[-1][:-1])
        qpaths = sorted(glob.glob(f"runs/**/q_{a.port}*.json", recursive=True),
                        key=lambda p: Path(p).stat().st_mtime)
        if not qpaths:
            return ''
        qp, mt = qpaths[-1], Path(qpaths[-1]).stat().st_mtime
        if _BRAIN_CACHE.get(qp, (0,))[0] != mt:
            data = json.loads(Path(qp).read_text())
            _BRAIN_CACHE[qp] = (mt, load_model(qp, data.get('schema'), data.get('actions', 6)),
                                data.get('actions', 6))
        _, table, n = _BRAIN_CACHE[qp]
        return '\n' + brain_line(table, obs, n)
    except Exception:
        return ''


def status_line(a: Agent) -> str:
    if not a.ok:
        return f":{a.port}  offline"
    s = a.status
    if s.get("_rl"):  # RL learner status (runs/rlstatus_<port>.json)
        evaluation = s.get('evaluation') or {}
        grade = (f"EVAL {evaluation.get('wins', 0)}/{evaluation['episodes']} greedy"
                 if evaluation.get('episodes') else 'EVAL not run')
        epsilon = s.get('epsilon')
        exploration = f'{epsilon:.2f}' if isinstance(epsilon, (int, float)) else '?'
        return (f":{a.port} {s.get('tag', '')} {s.get('phase', 'TRAIN')}"
                f" ep {s.get('generation', '?')} wins {s.get('wins', 0)} eps {exploration}"
                f" | {grade} | winavg {s.get('win_avg', '?')} steps {s.get('steps_total', '?')}"
                + _brain(a))
    goals = sum(1 for v in s.get("goals", {}).values() if v)
    bits = [f":{a.port}", f"step {s.get('step', '?')}",
            f"m{s.get('map', '?')}", f"({s.get('x', '?')},{s.get('y', '?')}) {s.get('facing', '?')}",
            f"hp {s.get('hp', '?')}", f"goals {goals}/{len(GOALS)}"]
    if s.get("in_battle"):
        bits.append("BATTLE")
    if s.get("paused"):
        bits.append("PAUSED")
    return "  ".join(bits)


def main() -> int:
    import tkinter as tk  # lazy: status_line() must import on headless hosts without Tk
    from PIL import ImageTk
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default=None, help="e.g. 8800-8807 or 8765,8800 (default: probe 8765 and 8800-8815)")
    ap.add_argument("--fps", type=float, default=15.0, help="polls per second per agent")
    ap.add_argument("--fixed-scale", type=int, default=None, help="pin tile scale; default auto-fits the window")
    a = ap.parse_args()

    if a.ports:
        ports = []
        for part in a.ports.split(","):
            if "-" in part:
                lo, hi = part.split("-", 1)
                ports.extend(range(int(lo), int(hi) + 1))
            else:
                ports.append(int(part))
    else:
        ports = [8765] + list(range(8800, 8816))

    try:  # Windows DPI awareness, or the window blurs at 125-150% scaling
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    agents = [Agent(p) for p in ports]
    stop = threading.Event()
    for ag in agents:
        threading.Thread(target=poll, args=(ag, a.fps, stop), daemon=True).start()

    root = tk.Tk()
    root.title("PokeAgent swarm")
    root.configure(bg=BG)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop.set(), root.destroy()))

    state = {"focus": None, "resize_at": 0.0}

    grid = tk.Frame(root, bg=BG)
    grid.pack(fill="both", expand=True)
    tiles: dict[int, dict] = {}
    for ag in agents:
        outer = tk.Frame(grid, bg=BORDER["dead"], padx=2, pady=2)
        img = tk.Label(outer, bg=BG)
        img.pack()
        txt = tk.Label(outer, text=f":{ag.port}", bg=BG, fg=DIM, font=("Consolas", 9), anchor="w")
        txt.pack(fill="x")
        tiles[ag.port] = {"outer": outer, "img": img, "txt": txt, "seq": -1}
        img.bind("<Button-1>", lambda _e, p=ag.port: set_focus(p))
        txt.bind("<Button-1>", lambda _e, p=ag.port: set_focus(p))

    def cols_for(n: int) -> int:
        return max(1, math.ceil(math.sqrt(n)))

    def grid_scale() -> int:
        if a.fixed_scale:
            return a.fixed_scale
        n = len(agents)
        cols = cols_for(n)
        rows = math.ceil(n / cols)
        w, h = max(root.winfo_width(), 400), max(root.winfo_height(), 300)
        return max(1, min(10, min(w // (cols * 164), h // (rows * 168))))

    def relayout() -> None:
        # every probed port keeps a tile (dead ones dim to 'offline'), so the grid is stable
        cols = cols_for(len(agents))
        for w in grid.winfo_children():
            w.grid_forget()
        for i, ag in enumerate(agents):
            tiles[ag.port]["outer"].grid(row=i // cols, column=i % cols, padx=2, pady=2, sticky="n")

    def set_focus(port: Optional[int]) -> None:
        state["focus"] = port
        if port is None:
            try:
                root.state("normal")  # back out: restore the grid-sized window
            except Exception:
                pass
            focus.pack_forget()
            grid.pack(fill="both", expand=True)
            relayout()
        else:
            grid.pack_forget()
            focus.pack(fill="both", expand=True)
            try:
                root.state("zoomed")  # click-in: maximize so the focused agent gets the whole screen
            except Exception:
                pass

    focus = tk.Frame(root, bg=BG)
    fimg = tk.Label(focus, bg=BG)
    fimg.pack(expand=True)
    ftxt = tk.Label(focus, bg=BG, fg=FG, font=("Consolas", 11), anchor="w", justify="left")
    ftxt.pack(fill="x", padx=8, pady=4)
    fimg.bind("<Button-1>", lambda _e: set_focus(None))
    focus.bind("<Button-1>", lambda _e: set_focus(None))
    ftxt.bind("<Button-1>", lambda _e: set_focus(None))
    root.bind("<Escape>", lambda _e: set_focus(None))
    root.bind("<Button-3>", lambda _e: set_focus(None))  # right-click anywhere: back out

    def on_resize(_e) -> None:
        state["resize_at"] = time.time() + 0.2  # debounce: redraw picks up the new scale

    root.bind("<Configure>", on_resize)

    def draw(ag: Agent, label: "tk.Label", scale: int) -> None:
        try:
            if ag.png and ag.raw:
                im = Image.frombytes("RGB", ag.dims, ag.png)
            elif ag.png:
                im = Image.open(io.BytesIO(ag.png))
            else:  # placeholder until the first frame lands: a dark box keeps the grid geometry fixed
                im = Image.new("RGB", (160, 144), (16, 16, 16))
            im = im.resize((160 * scale, 144 * scale), Image.NEAREST)
            ag.photo = ImageTk.PhotoImage(im)
            label.configure(image=ag.photo)
        except Exception:
            pass

    def focus_scale() -> int:
        if a.fixed_scale:
            return a.fixed_scale
        w, h = max(root.winfo_width(), 400), max(root.winfo_height(), 300)
        return max(1, min(16, min(w // 164, h // 200)))

    def redraw() -> None:
        resized = time.time() >= state["resize_at"] > 0
        if resized:
            state["resize_at"] = 0.0
        if state["focus"] is not None:
            ag = next((x for x in agents if x.port == state["focus"]), None)
            if ag:
                if ag.seq != tiles[ag.port]["seq"] or resized:
                    draw(ag, fimg, focus_scale())
                    tiles[ag.port]["seq"] = ag.seq
                s = ag.status
                if ag.ok and s:
                    ftxt.configure(text=status_line(ag) + "\n" +
                                   f"goals: {[k for k, v in s.get('goals', {}).items() if v]}\n"
                                   f"goal_steps: {s.get('goal_steps', {})}  goto: {s.get('goto')}")
        else:
            scale = grid_scale()
            for ag in agents:
                t = tiles[ag.port]
                if ag.seq != t["seq"] or resized:
                    draw(ag, t["img"], scale)
                    t["seq"] = ag.seq
                t["txt"].configure(text=status_line(ag), fg=(FG if ag.ok else DIM),
                                   wraplength=160 * scale, justify='left')
                border = (BORDER["dead"] if not ag.ok else
                          BORDER["battle"] if ag.status.get("in_battle") else
                          BORDER["paused"] if ag.status.get("paused") else BORDER["ok"])
                t["outer"].configure(bg=border)
        root.after(30, redraw)  # ~30ms tick: frames appear as soon as a poll lands

    relayout()
    root.after(200, redraw)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
