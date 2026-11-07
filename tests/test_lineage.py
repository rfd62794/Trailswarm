"""Lineage: statefp.lineage/is_organic, edit_class, stamp inheritance, promote, and the curriculum gate."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_ingest  # noqa: E402
import seg_store as ss  # noqa: E402
from test_legality import world as legal_world, KB, CATALOG, HM  # noqa: E402
from pokeagent import envelope, lineage, statefp  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402

ATT = {"run": "explore-a", "solved": True, "frames": 900, "steps": 30, "seed": 5, "starter": "squirtle",
       "explore_rate": 0.0, "box_pace": 8, "budget": 1500, "maps": [0x26], "tagged": True, "outside": 0, "est": False}


def _state(d, name, fp=None):
    p = d / name
    p.write_bytes(b"s")
    if fp is not None:
        statefp.write(p, {"v": 1, **fp})
    return p


def test_lineage_reads(tmp_path):
    assert statefp.lineage(_state(tmp_path, "a.state")) == "organic"                    # no sidecar: legacy
    assert statefp.lineage(_state(tmp_path, "b.state", {"synthetic": True})) == "synthetic"
    assert statefp.lineage(_state(tmp_path, "c.state", {"lineage": "promoted", "synthetic": True})) == "promoted"
    p = _state(tmp_path, "d.state", {"lineage": "promoted"})
    assert not statefp.is_synthetic(p) and not statefp.is_organic(p)
    assert statefp.is_synthetic(_state(tmp_path, "e.state", {"lineage": "synthetic"}))


def test_stamp_inherits_non_organic_lineage(tmp_path):
    src = _state(tmp_path, "src.state", {"lineage": "synthetic"})
    out = tmp_path / "out.state"
    fp = statefp.stamp(FakeEmulator({0xD35E: 1}), out, inherit=src)
    assert fp["lineage"] == "synthetic" and fp["parent"] == "src.state" and "synthetic" not in fp
    org = _state(tmp_path, "org.state", {"respawn": 5})
    fp = statefp.stamp(FakeEmulator({0xD35E: 1}), tmp_path / "o.state", inherit=org)
    assert "lineage" not in fp and "parent" not in fp
    fp = statefp.stamp(FakeEmulator({0xD35E: 1}), tmp_path / "p.state", inherit=_state(tmp_path, "pr.state", {"lineage": "promoted"}))
    assert fp["lineage"] == "promoted"


CAT = {"items": {"20": {"price": 300}, "63": {"price": 0}}}


def test_edit_class():
    ctx = {"money_before": 2000, "parent_lineage": "organic", "hp": [30, 79]}
    seen = {3, 5}
    assert lineage.edit_class({"heal": True}, ctx, CAT, seen) == "organic_equivalent"
    assert lineage.edit_class({"take": [[20, 2]]}, ctx, CAT, seen) == "organic_equivalent"
    assert lineage.edit_class({"set_hp": {0: 10}}, ctx, CAT, seen) == "organic_equivalent"      # damage
    assert lineage.edit_class({"set_hp": {0: 40}}, ctx, CAT, seen) == "shortcut"               # heal above current
    assert lineage.edit_class({"give": [[20, 5]], "money": 500}, ctx, CAT, seen) == "organic_equivalent"  # 1500 paid
    assert lineage.edit_class({"give": [[20, 5]], "money": 1000}, ctx, CAT, seen) == "shortcut"  # underpaid
    assert lineage.edit_class({"give": [[20, 5]]}, ctx, CAT, seen) == "shortcut"               # free give
    assert lineage.edit_class({"give": [[63, 1]], "money": 0}, ctx, CAT, seen) == "shortcut"   # price 0 item
    assert lineage.edit_class({"money": 5000}, ctx, CAT, seen) == "shortcut"                   # money increase
    assert lineage.edit_class({"money": 100}, ctx, CAT, seen) == "shortcut"                    # drop, no purchase
    assert lineage.edit_class({"respawn": 5}, ctx, CAT, seen) == "organic_equivalent"
    assert lineage.edit_class({"respawn": 9}, ctx, CAT, seen) == "shortcut"                    # never seen
    assert lineage.edit_class({"set_level": {0: 30}}, ctx, CAT, seen) == "shortcut"
    assert lineage.edit_class({"position": {"map": 1, "x": 1, "y": 1, "unsafe_pos": True}}, ctx, CAT, seen) == "shortcut"
    assert lineage.edit_class({}, ctx, CAT, seen) == "shortcut"


def _promote_world(tmp_path):
    end = tmp_path / "end.state"
    legal_world().save_state(end)
    statefp.stamp(legal_world(), end)
    return end


def test_promote_happy_path_and_refusals(tmp_path, monkeypatch):
    start = _state(tmp_path, "start.state", {"lineage": "synthetic", "edit_class": "organic_equivalent",
                                             "synthetic": True})
    end = _promote_world(tmp_path)
    env = envelope.build([tmp_path])
    ok, reasons = lineage.promote(end, start, legal_world(), KB, catalog=CATALOG, hm=HM, env=env)
    assert ok and reasons == []
    fp = statefp.read(end)
    assert fp["lineage"] == "promoted" and fp["parent"] == "start.state" and fp["promoted_from"] == "start.state"
    assert fp["legal"]["ok"] and "synthetic" not in fp
    # shortcut start: nothing written
    end2 = _promote_world(tmp_path)
    bad_start = _state(tmp_path, "bad.state", {"lineage": "synthetic", "edit_class": "shortcut", "synthetic": True})
    ok, reasons = lineage.promote(end2, bad_start, legal_world(), KB, env=env)
    assert not ok and any("organic_equivalent" in r for r in reasons)
    assert "promoted" not in (statefp.read(end2) or {})
    # illegal end: nothing written
    end3 = _promote_world(tmp_path)
    emu = legal_world()
    emu.memory[0xD347] = 0xAA                                                           # money not BCD
    ok, reasons = lineage.promote(end3, start, emu, KB, catalog=CATALOG, hm=HM, env=env)
    assert not ok and any("money:" in r for r in reasons)
    assert "promoted" not in (statefp.read(end3) or {})
    # out of envelope: nothing written
    end4 = _promote_world(tmp_path)
    tight = {"badges:2": {"lead": 1, "party": 1, "money": 1, "badges": 0, "bag_slots": 0, "heal_items": 0,
                          "respawns": []}}
    ok, reasons = lineage.promote(end4, start, legal_world(), KB, env=tight)
    assert not ok and any("envelope" in r or ">" in r for r in reasons)
    assert "promoted" not in (statefp.read(end4) or {})


def _job(root, tag):
    d = ss.job_dir(root, tag)
    d.mkdir(parents=True, exist_ok=True)
    (d / "maps.json").write_text("{}")
    (d / "bedroom.state").write_bytes(b"s")
    (d / "job.json").write_text(json.dumps({"start_name": "bedroom.state", "start_sha": ss.sha256(d / "bedroom.state")}))
    return d


def _seg(doc):
    return next(s for s in ss.layout(doc) if s.key == "potion")


def _run(root, name="explore-a", start="baseline"):
    run = root / "runs" / name
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"start": start}))
    (run / "end.state").write_bytes(b"END-" + name.encode())
    return run


def test_a_promoted_start_records_no_attempt_and_is_not_replayable(tmp_path):
    root, doc = tmp_path, ss.empty_doc()
    d = _job(root, "seg:potion:1-0")
    statefp.write(d / "bedroom.state", {"v": 1, "lineage": "promoted"})
    seg_ingest.record_attempt(root, doc, _seg(doc), dict(ATT), _run(root), "seg:potion:1-0")
    assert doc["stats"] == {}
    start = d / "bedroom.state"
    b = {"input": str(d / "maps.json"), "start": str(start), "start_sha": ss.sha256(start),
         "seed": 5, "starter": "squirtle", "explore_rate": 0.0, "box_pace": 8}
    assert ss.replayable(b) is False                                                     # promoted can never confirm


def test_a_promoted_checkpoint_may_start_a_segment(tmp_path):
    ck = tmp_path / "runs" / "checkpoints"
    ck.mkdir(parents=True)
    p = ck / "potion.state"
    p.write_bytes(b"s")
    statefp.write(p, {"v": 1, "lineage": "promoted", "map": 0x61, "party": [[179, 29, 79, 79]]})
    assert ss.ckpt_valid(tmp_path, "potion")                                             # not is_synthetic: MAY start a segment
    statefp.write(p, {"v": 1, "lineage": "synthetic", "map": 0x61, "party": [[179, 29, 79, 79]]})
    assert not ss.ckpt_valid(tmp_path, "potion")


def test_organic_start_is_unchanged(tmp_path):
    root, doc = tmp_path, ss.empty_doc()
    (root / "baselines").mkdir()
    (root / "baselines/bedroom.state").write_bytes(b"s")
    _job(root, "seg:potion:1-0")
    seg_ingest.record_attempt(root, doc, _seg(doc), dict(ATT), _run(root), "seg:potion:1-0")
    assert ss.stat(doc, "potion")["n"] == 1
