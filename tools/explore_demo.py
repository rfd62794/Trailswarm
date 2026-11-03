"""Learning explorer demo: one window (game left, console right), a rule-based agent that LEARNS the map.

    uv run python tools/explore_demo.py                  # from the repo root; needs baselines/bedroom.state
    uv run python tools/explore_demo.py --steps 400 --maps runs/maps.json

What it learns, and where it goes so the real framework can reuse it:
  runs/maps.json                 cumulative map memory (same schema Map_Memory_Directive adopts):
                                 per map id: visited tiles with counts, blocked (x,y,DIR), warps (x,y,DIR)->[map,x,y]
  runs/explore-<ts>/transitions.jsonl   one line per press: from, button, to, moved, textbox, source
Policy: if a text box is open (border tile 0x79 in the tile map) press A; otherwise pick the direction from the
current tile that is not known-blocked and leads to the least-visited tile. Human steering: click the window and
use arrows / a (A) / s (B) / Enter (START) / Shift (SELECT); p pauses the agent. Human presses are learned too.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.ram import read_state  # noqa: E402

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
CHARMAP = {0x7F: " ", 0xBA: "é", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xF4: ","}  # verified on the ROM
CHARMAP.update({0x80 + i: chr(65 + i) for i in range(26)})
CHARMAP.update({0xA0 + i: chr(97 + i) for i in range(26)})
CHARMAP.update({0xF6 + i: str(i) for i in range(10)})


def box_open(tilemap: bytes) -> bool:
    """A frame is open when a top-left corner tile is immediately followed by a top-edge tile."""
    i = tilemap.find(bytes([BORDER_TL, 0x7A]))
    return i >= 0


def box_text(tilemap: bytes) -> str:
    """Readable text of an open dialog box (rows 13-16 between the 0x7C borders), or ''."""
    rows = [tilemap[r * 20:(r + 1) * 20] for r in range(13, 17)]
    words = " ".join("".join(CHARMAP.get(b, "") for b in r[1:19]).strip() for r in rows)
    return " ".join(words.split())
KEYS = {"Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT", "a": "A", "s": "B",
        "Return": "START", "Shift_L": "SELECT", "Shift_R": "SELECT"}
TILEMAP, TILEMAP_LEN, BORDER_TL = 0xC3A0, 360, 0x79


class MapMemory:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"maps": {}}

    def m(self, map_id: int) -> dict:
        return self.data["maps"].setdefault(str(map_id), {"visited": {}, "blocked": [], "warps": {}, "last_seen": 0})

    def visit(self, map_id, x, y, step):
        d = self.m(map_id); d["visited"][f"{x},{y}"] = d["visited"].get(f"{x},{y}", 0) + 1; d["last_seen"] = step

    def learn(self, before, button, after, *, confirmed: bool) -> str:
        """Record what a press did. A move that fails is only 'blocked' once CONFIRMED (same press from
        the same tile failed twice in a row); a single failure can be a turn-in-place or a warp fade."""
        (m0, x0, y0), (m1, x1, y1) = before, after
        if button not in DIRS:
            return "pressed"
        key = f"{x0},{y0},{button}"
        blocked = self.m(m0)["blocked"]
        if m1 != m0:
            self.m(m0)["warps"][key] = [m1, x1, y1]; return f"WARP to map 0x{m1:02X} ({x1},{y1})"
        if (x1, y1) == (x0, y0):
            if not confirmed:
                return "no move (turned? fading?) - will retry once before calling it blocked"
            if key not in blocked:
                blocked.append(key)
            return "blocked (confirmed)"
        if key in blocked:
            blocked.remove(key)  # it was a false 'blocked' (learned during a fade); forget it
            return "moved - cleared a false wall"
        return "moved"

    def interact(self, map_id, x, y, facing, text: str):
        d = self.m(map_id).setdefault("interactions", {})
        e = d.setdefault(f"{x},{y},{facing}", {"count": 0, "text": ""})
        e["count"] += 1
        if text and not e["text"]:
            e["text"] = text[:120]

    def interaction_known(self, map_id, x, y, facing) -> bool:
        return f"{x},{y},{facing}" in self.m(map_id).get("interactions", {})

    def choose(self, map_id, x, y, facing: str) -> tuple[str, str]:
        d = self.m(map_id); best = None
        tried = [n for n in DIRS if f"{x},{y},{n}" in d["blocked"]]
        # Something blocks the way we face and we never talked to it: that is an interaction point candidate.
        if facing in tried and not self.interaction_known(map_id, x, y, facing):
            return "A", f"at ({x},{y}) facing {facing} is blocked and untested: pressing A to see if it talks"
        for name, (dx, dy) in DIRS.items():
            if name in tried:
                continue
            visits = d["visited"].get(f"{x + dx},{y + dy}", 0)
            if best is None or visits < best[0]:
                best = (visits, name)
        if best is None:
            return "A", "every direction known blocked: pressing A to look around"
        why = f"at ({x},{y}) blocked={tried or 'none'}; {best[1]} leads to a tile seen {best[0]}x"
        return best[1], why

    def save(self):
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--frames-per-step", type=int, default=30)
    a = ap.parse_args(argv)

    run_dir = Path("runs") / f"explore-{time.strftime('%Y%m%d-%H%M%S')}"; run_dir.mkdir(parents=True)
    trans = (run_dir / "transitions.jsonl").open("a", encoding="utf-8")
    mem = MapMemory(Path(a.maps))
    emu = PyBoyEmulator(Path(a.rom), headless=True)
    emu.tick(60); emu.load_state(Path(a.state)); emu.tick(30)

    root = tk.Tk(); root.title("PokeAgent explorer demo - click here, arrows/a/s/Enter/Shift steer, p pauses")
    root.configure(bg="#111")
    screen = tk.Label(root, bg="#111", bd=0); screen.grid(row=0, column=0, padx=8, pady=8)
    con = tk.Text(root, width=78, height=28, bg="#0b0b0b", fg="#d8d8d8", font=("Consolas", 10), bd=0, padx=10, pady=8, wrap="word")
    con.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ns")
    for tag, col in {"hdr": "#7fd1ff", "why": "#c9f29b", "btn": "#ffd166", "res": "#ff9f7f", "human": "#f78fff"}.items():
        con.tag_config(tag, foreground=col)
    st = {"step": 0, "frame": 0, "photo": None, "paused": False, "done": False,
          "facing": "DOWN", "last_fail": None, "box_streak": 0, "settle": 0}

    def log(t, tag=None):
        con.insert("end", t + "\n", tag); con.see("end")

    def pos():
        s = read_state(emu); return (s.map_id, s.x, s.y)

    def do_press(name: str, source: str, why: str):
        before = pos(); st["step"] += 1
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        box_before = box_open(tm)
        emu.press(Button[name]); emu.tick(8)
        after = pos()
        tm2 = emu.read_range(TILEMAP, TILEMAP_LEN)
        box_after = box_open(tm2)
        text = box_text(tm2) if box_after else ""
        if name in DIRS:
            st["facing"] = name
        if box_before:
            result = f"text box: advanced{' -> closed' if not box_after else ''}"
        elif name == "A":
            # Record the A press either way, so a silent wall is tested once and never again.
            mem.interact(before[0], before[1], before[2], st["facing"], text if box_after else "")
            result = (f"INTERACTION at ({before[1]},{before[2]}) facing {st['facing']}: \"{text[:60]}\""
                      if box_after else f"nothing to interact with facing {st['facing']} (remembered)")
        else:
            fail_key = (before, name)
            confirmed = st["last_fail"] == fail_key
            result = mem.learn(before, name, after, confirmed=confirmed)
            st["last_fail"] = fail_key if (name in DIRS and after == before) else None
            if after[0] != before[0]:
                st["settle"] = 90  # map changed: let the fade finish before the next press
        mem.visit(after[0], after[1], after[2], st["step"])
        st["box_streak"] = st["box_streak"] + 1 if box_after else 0
        trans.write(json.dumps({"step": st["step"], "from": list(before), "button": name, "to": list(after),
                                "moved": before != after, "textbox": "dialog" if box_before else "none",
                                "text": text, "facing": st["facing"], "source": source}) + "\n")
        trans.flush()  # the later process reads this file while the demo is still running
        mm = mem.m(after[0])
        log(f"--- step {st['step']}/{a.steps}  map=0x{after[0]:02X} pos=({after[1]},{after[2]}) facing {st['facing']}  "
            f"learned: {len(mm['visited'])} tiles, {len(mm['blocked'])} walls, {len(mm['warps'])} warps, "
            f"{len(mm.get('interactions', {}))} interactions", "hdr")
        log(f"{'human:   ' if source == 'human' else 'thinking:'} {why}", "human" if source == "human" else "why")
        log(f"button:   {name:<8} result: {result}\n", "btn")
        if st["step"] % 10 == 0:
            mem.save()
        if st["step"] >= a.steps:
            st["done"] = True; mem.save(); log(f"done. map memory saved to {a.maps}; transitions in {run_dir}", "hdr")

    def agent_step():
        if st["settle"] > 0:
            st["settle"] -= a.frames_per_step; return
        m, x, y = pos()
        if box_open(emu.read_range(TILEMAP, TILEMAP_LEN)):
            if st["box_streak"] >= 8:
                do_press("B", "agent", "a box has stayed open for 8 presses (a menu?) - pressing B to back out"); return
            do_press("A", "agent", "a text box is open - finishing the interaction before moving"); return
        name, why = mem.choose(m, x, y, st["facing"]); do_press(name, "agent", why)

    def on_key(ev):
        if ev.keysym == "p":
            st["paused"] = not st["paused"]; log(f"[agent {'paused' if st['paused'] else 'resumed'}]", "res"); return
        name = KEYS.get(ev.keysym)
        if name:
            do_press(name, "human", f"you pressed {name}")

    def frame():
        if st["done"]:
            return
        img = emu.screenshot().resize((480, 432), Image.NEAREST)  # screenshot renders one frame
        st["photo"] = ImageTk.PhotoImage(img); screen.configure(image=st["photo"])
        st["frame"] += 1
        if not st["paused"] and st["frame"] % a.frames_per_step == 0:
            agent_step()
        root.after(16, frame)

    root.bind("<Key>", on_key)
    log("Explorer demo. Rule-based agent learning the map; your key presses are learned too. Click the window to steer.\n", "hdr")
    log(f"map memory: {a.maps} ({len(mem.data['maps'])} maps known so far)\n", "res")
    root.after(300, frame)
    root.protocol("WM_DELETE_WINDOW", lambda: (mem.save(), trans.close(), emu.close(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
