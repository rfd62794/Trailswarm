"""record() over a stub emulator: counters, the contract layout, the full-store stop, and the
tool's import-safety plus --out guard."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.vision.positions import PositionLog
from pokeagent.vision.record import record
from pokeagent.vision.source_red import RedSource
from pokeagent.vision.store import Store

ROOT = Path(__file__).resolve().parents[1]
PLAYER = (1, 0, 5, 6, 0)


class StubEmu(FakeEmulator):
    """FakeEmulator whose frames differ per tick, so crops don't all dedupe to one."""

    def frame_rgb(self):
        rng = np.random.default_rng(self.frames)
        return rng.integers(0, 256, 144 * 160 * 3, dtype=np.uint8).tobytes()


def red_mem(*slots, tile=0):
    mem = {0xD35E: 5, 0xD361: 6, 0xD362: 5, 0xD367: 4}
    for i, (pic, img, nx, ny, move) in enumerate(slots):
        mem[0xC100 + 16 * i], mem[0xC100 + 16 * i + 2] = pic, img
        mem[0xC200 + 16 * i + 4], mem[0xC200 + 16 * i + 5], mem[0xC200 + 16 * i + 6] = ny + 4, nx + 4, move
    mem.update({0x9800 + i: tile for i in range(1024)})
    return StubEmu(mem)


def test_record_writes_the_contract_layout(tmp_path):
    emu = red_mem(PLAYER, (13, 0, 6, 6, 0xFE))
    store, log = Store(tmp_path), PositionLog(tmp_path)
    counters = record(emu, RedSource(), store, log, [(Button.UP, 8, 16)],
                      sample_every=24, thumb_every=1, run="t")
    log.close()
    store.flush()
    assert counters == {"presses": 1, "frames": 24, "samples": 1, "skipped": 0, "stopped": False}
    rows = [json.loads(ln) for ln in (tmp_path / "samples.jsonl").read_text().splitlines()]
    sprites = {r["label"]: r for r in rows if r["kind"] == "sprite"}
    assert set(sprites) == {1, 13} and sprites[13]["coarse"] == "npc" and sprites[13]["bank"] is None
    assert (tmp_path / "images" / sprites[13]["id"][:2] / f"{sprites[13]['id']}.png").is_file()
    tiles = [r for r in rows if r["kind"] == "tile"]
    assert tiles and all(r["bank"] == 4 and r["w"] == 8 and r["h"] == 8 for r in tiles)
    pos = [json.loads(ln) for ln in (tmp_path / "positions.jsonl").read_text().splitlines()]
    assert pos == [{"f": 32, "run": "t", "area": "map-5", "player": [5, 6],
                    "ents": [["slot0", 1, 5, 6, 0], ["slot1", 13, 6, 6, 254]]}]
    thumbs = [json.loads(ln) for ln in (tmp_path / "thumbs.jsonl").read_text().splitlines()]
    assert thumbs[0]["area"] == "map-5" and thumbs[0]["cell"] == "1,1" and thumbs[0]["pos"] == [5, 6]
    assert list((tmp_path / "thumbs").rglob("*.png"))
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["frames_seen"] == 24 and meta["positions_capped"] is False


def test_record_skips_flagged_frames_and_counts_chunks(tmp_path):
    emu = red_mem()                                            # no sane slot: every frame skipped
    store, log = Store(tmp_path), PositionLog(tmp_path)
    counters = record(emu, RedSource(), store, log, [(Button.UP, 8, 16)], sample_every=8)
    log.close()
    assert counters == {"presses": 1, "frames": 24, "samples": 0, "skipped": 3, "stopped": False}
    assert not (tmp_path / "positions.jsonl").read_text()


def test_record_stops_when_store_full_and_log_capped(tmp_path):
    emu = red_mem(PLAYER)
    store = Store(tmp_path, max_bytes=0)
    log = PositionLog(tmp_path, max_bytes=0)
    counters = record(emu, RedSource(), store, log,
                    [(Button.UP, 8, 16), (Button.DOWN, 8, 16), (Button.LEFT, 8, 16)],
                    sample_every=24)
    log.close()
    assert counters["stopped"] and counters["presses"] == 1     # stopped cleanly, mid-stream


def _load_tool():
    spec = importlib.util.spec_from_file_location("vision_record_tool", ROOT / "tools" / "vision_record.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tool_imports_without_importing_pyboy():
    before = set(sys.modules)
    mod = _load_tool()
    new = {m for m in sys.modules if m not in before}
    assert mod and not any(m == "pyboy" or m.startswith("pyboy.") for m in new)


def test_tool_rejects_an_out_outside_runs(tmp_path):
    mod = _load_tool()
    assert mod.out_in_runs(Path("runs/vision/pokemon-red"), Path.cwd())
    assert not mod.out_in_runs(tmp_path / "elsewhere", Path.cwd())
    assert not mod.out_in_runs(Path("../outside"), Path.cwd())
    assert mod.main(["--game", "pokemon-red", "--rom", "missing.gb", "--out", str(tmp_path)]) == 2
