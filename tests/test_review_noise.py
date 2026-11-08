"""Loop-noise fixes: collapsed loop groups, reserved events under truncation, the unclassified
filter, and the swarm --since filter that skips dirs before opening meta.json."""
import json
from datetime import datetime
from pathlib import Path

from pokeagent.review import swarm, timeline
from pokeagent.review.loops import LONG_LOOP_ROWS, collapse_loops, find_loops


def _blocked(step, x=11, y=32, moved=False):
    return {"step": step, "from": [35, x, y], "button": "UP", "to": [35, x, y],
            "moved": moved, "textbox": "none", "text": ""}


def _episodes_57():
    """57 separate 6-row blocked runs at the same key, each cut off by one moved press."""
    rows, step = [], 0
    for _ in range(57):
        for _ in range(6):
            rows.append(_blocked(step))
            step += 1
        rows.append({"step": step, "from": [35, 11, 31], "button": "DOWN", "to": [35, 11, 32],
                     "moved": True, "textbox": "none", "text": ""})
        step += 1
    return rows


def test_57_same_key_episodes_collapse_to_one_group():
    eps = find_loops(_episodes_57())
    assert len(eps) == 57 and all(e["presses"] == 6 for e in eps)
    groups = collapse_loops(eps)
    assert len(groups) == 1
    g = groups[0]
    assert (g["kind"], g["count"], g["total_presses"], g["max_presses"]) == ("blocked_loop", 57, 342, 6)
    assert (g["step"], g["end_step"], g["long"]) == (0, 56 * 7 + 5, False)
    assert g["key"] == {"button": "UP", "map": 35, "x": 11, "y": 32}


def test_different_keys_stay_separate_and_long_is_flagged():
    rows = _episodes_57()[:6] + [_blocked(100 + i, x=3, y=4) for i in range(LONG_LOOP_ROWS)]
    groups = collapse_loops(find_loops(rows))
    assert [(g["key"]["x"], g["count"], g["long"]) for g in groups] == [(11, 1, False), (3, 1, True)]


def test_build_events_emits_one_loop_event_per_group():
    class D:  # minimal RunData stand-in: build_events only reads these attributes
        goal_frames, milestones, battles, after_victory, levels, dossier = [], {}, [], [], [], None
        name = "x"
        decisions = []
        transitions = _episodes_57()
    from pokeagent.review.events import build_events
    loops = [e for e in build_events(D) if e["kind"] == "loop"]
    assert len(loops) == 1 and (loops[0]["count"], loops[0]["presses"]) == (57, 342)


def test_reserved_events_survive_truncation():
    battles = [{"kind": "battle", "step": s, "battle_kind": 1} for s in range(1, 300)]
    stall = {"kind": "stall", "step": 500}
    blackout = {"kind": "blackout", "step": 501}
    long_loop = {"kind": "loop", "step": 450, "max_presses": 40}   # break-length, late in the run
    short_loop = {"kind": "loop", "step": 451, "max_presses": 6}
    events = sorted(battles + [stall, blackout, long_loop, short_loop],
                    key=lambda e: (e["step"], e["kind"]))
    kept, omitted = timeline.truncate_events(events, 10)
    assert len(kept) == 10 and omitted == len(events) - 10
    # the reserved events sit at the END of the run; a naive head-truncation would drop them
    assert stall in kept and blackout in kept and long_loop in kept
    assert short_loop not in kept
    assert [e["step"] for e in kept] == sorted(e["step"] for e in kept)


def test_truncation_noop_under_cap():
    events = [{"kind": "map", "step": 1}]
    assert timeline.truncate_events(events, 5) == (events, 0)


def test_unclassified_keeps_rare_heal_buy_adjacent_names_only():
    decisions = [{"rule": "frontier"}] * 90 + [{"rule": "item_stock"}] * 3 \
        + [{"rule": "fight"}] * 4 + [{"rule": "mart_visit"}] * 3
    decisions += [{"rule": "center_wait"}] * 0
    names = [r["rule"] for r in timeline._unclassified(decisions)]
    assert names == ["item_stock", "mart_visit"]   # frontier >5%, fight not adjacent


def test_swarm_since_skips_old_dirs_without_opening_meta(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    for name in ("explore-20261107-100000-1", "explore-20261107-160000-2"):
        d = runs / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"stop_at_goal": "gyarados", "steps": 5}))
    opened = []
    real = swarm.load_json

    def spy(path):
        if Path(path).name == "meta.json":
            opened.append(Path(path).parent.name)
        return real(path)

    monkeypatch.setattr(swarm, "load_json", spy)
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", lambda *a, **k: [])
    s = swarm.summarise(runs, datetime(2026, 11, 7, 15, 0))
    assert opened == ["explore-20261107-160000-2"]
    assert s["runs"]["count"] == 1
