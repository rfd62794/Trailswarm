"""PC / bag probe: use the bedroom PC to withdraw the POTION and watch which RAM bytes change.

    uv run python tools/probe_pc.py            # headless; uses baselines/bedroom.state and runs/maps.json

Reuses the explorer's learned map (runs/maps.json): BFS over visited tiles and known walls to reach each
candidate spot, press A facing the wall, read the dialog from the tile map, and stop at the one that says PC.
Then: WITHDRAW ITEM -> first item -> confirm -> LOG OFF, snapshotting WRAM before and after, and print the
bytes in 0xD000-0xD800 that changed (bag is believed near 0xD31D: count, then item id/qty pairs, 0xFF end).
Writes runs/probe-pc-<ts>.json with every screen text and the diff, for the hex directive to consume.
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.ram import RAM_MAP, read_state  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explore_demo import DIRS, box_open, box_text, frame_lines, is_menu  # noqa: E402

TILEMAP, TILEMAP_LEN = 0xC3A0, 360
NAMES = {addr: n for n, addr in RAM_MAP.items()}
NAMES.update({0xD31D: "wNumBagItems?", 0xD31E: "wBagItems?", 0xD53A: "wNumBoxItems?", 0xD53B: "wBoxItems?"})
BEDROOM = 38


def bfs(mem_map: dict, start: tuple, goal: tuple) -> list[str] | None:
    visited, blocked = mem_map["visited"], set(mem_map["blocked"])
    prev = {start: None}; q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for name, (dx, dy) in DIRS.items():
            nxt = (cur[0] + dx, cur[1] + dy)
            if f"{cur[0]},{cur[1]},{name}" in blocked or f"{nxt[0]},{nxt[1]}" not in visited or nxt in prev:
                continue
            prev[nxt] = (cur, name); q.append(nxt)
    if goal not in prev:
        return None
    path, node = [], goal
    while prev[node]:
        node, name = prev[node]; path.append(name)
    return path[::-1]


def main() -> int:
    maps = json.loads(Path("runs/maps.json").read_text())["maps"][str(BEDROOM)]
    emu = PyBoyEmulator(Path("roms/Pokemon Red.gb"), headless=True)
    emu.tick(60); emu.load_state(Path("baselines/bedroom.state")); emu.tick(30)
    record = {"texts": [], "steps": []}

    def pos():
        s = read_state(emu); return (s.x, s.y)

    def press(b, n=1, settle=0):
        for _ in range(n):
            emu.press(Button[b]); emu.tick(settle)
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        txt = box_text(tm) if box_open(tm) else ""
        record["steps"].append({"button": b, "pos": pos(), "text": txt})
        if txt:
            record["texts"].append(txt)
        return txt

    def walk(path):
        for d in path:
            before = pos(); press(d, settle=4)
            if pos() == before:
                press(d, settle=4)  # first press may only turn

    def close_all():
        for _ in range(12):
            if not box_open(emu.read_range(TILEMAP, TILEMAP_LEN)):
                return
            press("B", settle=4)

    # 1. find the PC: candidate = visited tile with a blocked edge; try the upper-left area first
    cands = []
    for key in maps["blocked"]:
        x, y, d = key.split(","); cands.append(((int(x), int(y)), d))
    cands.sort(key=lambda c: (c[0][1] + c[0][0]))
    pc_spot = None
    for (tile, d) in cands:
        path = bfs(maps, pos(), tile)
        if path is None:
            continue
        walk(path); press(d, settle=4)  # face the wall (may bump)
        txt = press("A", settle=20)
        print(f"at {tile} facing {d}: {txt!r}")
        if "PC" in txt.upper():
            pc_spot = (tile, d); break
        close_all()
    if not pc_spot:
        print("PC not found from learned tiles; let the explorer run longer"); emu.close(); return 1

    # 2. snapshot, withdraw, snapshot
    snap0 = emu.read_range(0xD000, 0x800)
    for _ in range(6):               # advance "turned on the PC" text until a menu with a cursor shows
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        if is_menu(tm):
            break
        press("A", settle=20)
    print("menu:", frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN)))
    press("A", settle=20)            # cursor should be on WITHDRAW ITEM
    print("after choose:", frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN)))
    press("A", settle=20)            # first item
    print("after item:", frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN)))
    press("A", settle=20)            # quantity / confirm
    print("after confirm:", frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN)))
    for _ in range(3):
        press("A", settle=20)
    close_all()
    snap1 = emu.read_range(0xD000, 0x800)
    diff = [(0xD000 + i, a, b) for i, (a, b) in enumerate(zip(snap0, snap1)) if a != b]
    print(f"\n{len(diff)} bytes changed in D000-D7FF:")
    for addr, a, b in diff[:60]:
        print(f"  {addr:04X} {NAMES.get(addr, ''):16} {a:02X} -> {b:02X}")
    record["diff"] = [{"addr": f"0x{a:04X}", "old": o, "new": n, "name": NAMES.get(a, "")} for a, o, n in diff]
    record["pc_spot"] = pc_spot
    out = Path("runs") / f"probe-pc-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(record, indent=1)); print("wrote", out)
    emu.close(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
