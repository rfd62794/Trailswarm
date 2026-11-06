from pathlib import Path

from pokeagent.ramlab import findings as F
from pokeagent.ramlab.labels import LabelIndex
from pokeagent.ramlab.mine import mine
from pokeagent.ramlab.verify import judge, passed, run_checks

ENTRIES = [
    {"name": "wPlayerMoney", "addr": "0xD347", "size": 1, "region": "items", "verified": False},
    {"name": "wTileMap", "addr": "0xC3A0", "size": 360, "region": "text", "verified": False},
]


def records():
    recs = []
    for i in range(4):
        recs.append({"run": f"r{i % 2}", "step": 10 + i, "ev": ["money"], "map": 1, "x": 0, "y": 0, "vals": {},
                     "d": [[0xD347, 1, 2]]})
    for i in range(8):
        recs.append({"run": "r0", "step": 50 + i, "ev": ["step"], "map": 1, "x": 0, "y": 0, "vals": {}, "d": [[0xD362, i, i + 1]]})
    return recs


class FakeReplayer:
    """Replays by table: with the press the byte goes 1->2; without it nothing moves (set `leaky` to break control)."""

    def __init__(self, leaky=False, drift=False, dead=False):
        self.leaky, self.drift, self.dead = leaky, drift, dead

    def pre_states(self, run_dir, steps):
        return {s: Path(f"{run_dir.name}_{s}") for s in steps}

    def branches(self, pre, press, gap, addrs):
        pre_v = 9 if self.drift else 1
        ev = {a: [pre_v, pre_v, pre_v if self.dead else 2] for a in addrs}
        ct = {a: [pre_v, pre_v, 2 if self.leaky else pre_v] for a in addrs}
        return ev, ct


def setup(tmp_path, monkeypatch):
    import pokeagent.ramlab.verify as V
    monkeypatch.setattr(V, "load_trace", lambda d: ({}, [(i * 40, "a", 8, 16) for i in range(200)]))
    return {"r0": tmp_path / "r0", "r1": tmp_path / "r1"}


def test_judge_and_pass_rule():
    j = judge("inc1", {}, 1, [1, 1, 2], [1, 1, 1])
    assert j == {"in_sync": True, "event_ok": True, "control_clean": True}
    assert judge("inc1", {}, 1, [1, 1, 2], [1, 2, 2])["control_clean"] is False
    assert judge("inc1", {}, 5, [1, 1, 2], [1, 1, 1])["in_sync"] is False
    a, b = {**j, "run": "a"}, {**j, "run": "b"}
    assert passed([a, b]) and not passed([a])                    # one witness is not enough
    assert not passed([a, {**a, "step": 2}])                     # two witnesses from ONE run are not enough
    assert not passed([a, {**b, "control_clean": False}])        # time-driven does not verify
    assert not passed([a, b, {**a, "event_ok": False}, {**b, "event_ok": False}])


def cand(kind, examples):
    from pokeagent.ramlab.mine import Candidate
    return Candidate("e", 1, 5, 1, 0, 1, kind, 1, 2, 1, examples)


def test_weak_kinds_never_verify():
    from pokeagent.ramlab.verify import weak_kind
    assert weak_kind(cand("const:185", [(0, 185)]))
    assert weak_kind(cand("zero", [(1, 0), (1, 0)])) and not weak_kind(cand("zero", [(201, 0), (202, 0)]))
    assert weak_kind(cand("copy:battle_kind", [(0, 1), (0, 2)])) and not weak_kind(cand("copy:enemy_species", [(0, 165)]))
    assert not weak_kind(cand("inc1", [(1, 2)])) and not weak_kind(cand("set_bit:0", [(0, 1)]))


def test_verify_gate_flips_only_on_a_passing_replay(tmp_path, monkeypatch):
    runs = setup(tmp_path, monkeypatch)
    recs = records()
    cands = [c for c in mine(recs, 3) if c.event == "money"]
    labels = LabelIndex(ENTRIES)
    good, _ = run_checks(cands, recs, runs, FakeReplayer(), labels)
    assert good[0]["verified"] and good[0]["status"] == "confirms" and good[0]["label"] == "wPlayerMoney"
    assert "press-driven" in good[0]["evidence"] and "2 run(s)" in good[0]["evidence"]
    leaky, _ = run_checks(cands, recs, runs, FakeReplayer(leaky=True), labels)
    assert not leaky[0]["verified"] and "time-driven" in leaky[0]["evidence"]       # unverified, but not a failure
    assert leaky[0]["replay"]["passed"] == leaky[0]["replay"]["witnesses"]
    for bad in (FakeReplayer(drift=True), FakeReplayer(dead=True)):
        res, _ = run_checks(cands, recs, runs, bad, labels)
        assert not res[0]["verified"]
    entries = [dict(e) for e in ENTRIES]
    assert F.apply_to_map(entries, {"findings": good}) == 1
    assert good[0]["flipped_label"] and "e.g. 1->2" in good[0]["evidence"]
    assert entries[0]["verified"] and "replay" in entries[0]["evidence"] and not entries[1].get("verified")
    entries2 = [dict(e) for e in ENTRIES]
    res, _ = run_checks(cands, recs, runs, FakeReplayer(dead=True), labels)
    assert F.apply_to_map(entries2, {"findings": res}) == 0 and not entries2[0].get("verified")


def test_apply_to_map_region_and_byte_coverage_rules():
    def f(label, addr):
        return {"verified": True, "status": "confirms", "label": label, "addr": addr, "evidence": "x"}
    entries = [{"name": "wAudioThing", "addr": "0xC0EF", "size": 1, "region": "audio", "verified": False},
               {"name": "wMoney3", "addr": "0xD347", "size": 3, "region": "items", "verified": False},
               {"name": "wOne", "addr": "0xD100", "size": 1, "region": "map", "verified": False}]
    data = {"findings": [f("wAudioThing", "0xC0EF"), f("wMoney3", "0xD347"), f("wOne", "0xD100")]}
    assert F.apply_to_map(entries, data) == 1 and entries[2]["verified"]            # audio and a 1/3-covered array held back
    data["findings"] += [f("wMoney3", "0xD348"), f("wMoney3", "0xD349")]
    assert F.apply_to_map(entries, data) == 1 and entries[1]["verified"] and not entries[0]["verified"]


def test_big_labels_are_not_flipped(tmp_path):
    entries = [{"name": "wTileMap", "addr": "0xC3A0", "size": 360, "region": "text", "verified": False}]
    f = {"verified": True, "status": "confirms", "label": "wTileMap", "addr": "0xC3A0", "evidence": "x"}
    assert F.apply_to_map(entries, {"findings": [f]}) == 0


def test_upsert_never_downgrades():
    d = {"findings": [], "failed": []}
    F.upsert(d, {"event": "money", "addr": "0xD347", "verified": True})
    F.upsert(d, {"event": "money", "addr": "0xD347", "verified": False})
    assert d["findings"][0]["verified"] is True
