"""Scripted-state probe: from ONE saved state, replay a script of labelled events headlessly and
diff WRAM around each.

Noise control: before the events, the same state is loaded ``repeat`` times and ticked
``idle_frames`` with no input; every byte that changes is the time-driven noise set. Each event
then runs from a freshly loaded state ``repeat`` times; a byte is a result only if it changed in
the event, the same way (same before/after) in every repeat, and is not in the noise set.
Results split into ``unlabeled`` (inside a gaps.py gap) and ``labelled`` (inside a map entry,
counted only). probe.json + report.txt are written under
``<out root>/ramprobe-<game>-<state stem>-<YYYYMMDD-HHMM>/``. Nothing here names a game, an
address or a pokered label.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pokeagent.emulator import Button
from pokeagent.ramlab.gaps import summary as gap_summary, wram_gaps
from pokeagent.ramlab.labels import LabelIndex

WRAM_LO, WRAM_LEN = 0xC000, 0x2000
MAX_LISTED = 200              # cap on unlabeled bytes listed per event


def _snap(emu) -> bytes:
    return bytes(emu.read_range(WRAM_LO, WRAM_LEN))


def _diff(pre: bytes, post: bytes) -> dict[int, tuple[int, int]]:
    return {i: (pre[i], post[i]) for i in range(len(pre)) if pre[i] != post[i]}


def _noise(emu, state: Path, repeat: int, idle_frames: int) -> set[int]:
    """Snapshot offsets that change over `repeat` fresh loads of `state` + `idle_frames`, no input."""
    out: set[int] = set()
    for _ in range(max(1, repeat)):
        emu.load_state(state)
        pre = _snap(emu)
        emu.tick(idle_frames)
        out |= _diff(pre, _snap(emu)).keys()
    return out


def _event_diffs(emu, state: Path, ev: dict, repeat: int, noise: set[int]) -> dict[int, tuple[int, int]]:
    """Offsets that changed the same way in every repeat of this event, minus the noise set."""
    keep: dict[int, tuple[int, int]] | None = None
    for _ in range(max(1, repeat)):
        emu.load_state(state)
        pre = _snap(emu)
        for name in ev["presses"]:
            emu.press(Button(name), settle_frames=int(ev.get("settle", 60)))
        d = _diff(pre, _snap(emu))
        keep = d if keep is None else {o: ba for o, ba in keep.items() if d.get(o) == ba}
    return {o: ba for o, ba in (keep or {}).items() if o not in noise}


def _report_text(rep: dict) -> str:
    g = rep["gaps"]
    lines = [f"probe {rep['state']} ({rep['game']})  sha1 {rep['state_sha1']}",
             f"noise set: {rep['noise']} bytes; "
             f"gaps: {g['unlabeled']} unlabeled bytes in {g['gaps']} gaps, "
             f"{g['covered']} of {g['total']} covered", ""]
    for ev in rep["events"]:
        more = f" (first {len(ev['unlabeled'])} listed)" if ev["unlabeled_total"] > len(ev["unlabeled"]) else ""
        lines.append(f"{ev['label']}: {ev['unlabeled_total']} unlabeled{more}, labelled {ev['labelled']}")
        lines += [f"  0x{r['addr']:04X} {r['before']}->{r['after']}" for r in ev["unlabeled"]]
    return "\n".join(lines) + "\n"


def probe_run(emu, state: Path, script: dict, entries: list[dict], out_root: Path, game: str,
              *, stamp: str | None = None) -> Path:
    """Run the script from ``state`` and write probe.json + report.txt into the run dir."""
    state = Path(state)
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M")
    run_dir = Path(out_root) / f"ramprobe-{game}-{state.stem}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    repeat = int(script.get("repeat", 3))
    noise = _noise(emu, state, repeat, int(script.get("idle_frames", 30)))
    gaps = wram_gaps(entries)
    labels = LabelIndex(entries)
    events = []
    for ev in script["events"]:
        label = ev["label"]
        unl, lab = [], {}
        for off, (b, a) in sorted(_event_diffs(emu, state, ev, repeat, noise).items()):
            addr = WRAM_LO + off
            if any(g <= addr < g + n for g, n in gaps):
                unl.append({"addr": addr, "before": b, "after": a, "label": label})
            else:
                lb = labels.at(addr)
                key = lb.name if lb else f"0x{addr:04X}"
                lab[key] = lab.get(key, 0) + 1
        events.append({"label": label, "unlabeled": unl[:MAX_LISTED],
                       "unlabeled_total": len(unl), "labelled": dict(sorted(lab.items()))})
    rep = {"version": script.get("version", 1), "game": game, "state": state.name,
           "state_sha1": hashlib.sha1(state.read_bytes()).hexdigest(),
           "noise": len(noise), "gaps": gap_summary(entries), "events": events}
    (run_dir / "probe.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    (run_dir / "report.txt").write_text(_report_text(rep), encoding="utf-8")
    return run_dir
