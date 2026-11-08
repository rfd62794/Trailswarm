"""merge_trainers: shared per-ROM trainer knowledge - union, non-empty wins, flag_bit precedence and
conflicts, provenance (synthetic is UNCONFIRMED; unknown never promotes), idempotent, never 'beaten'."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import swarm_merge as sm  # noqa: E402


def _entry(**kw):
    return {"cls": "LASS", "party": 7, "prize": 210, "xp": 300.0, "flag_bit": None,
            "provenance": "organic", **kw}


def test_union_keeps_non_empty_and_never_carries_beaten():
    dst = {}
    src = {"trainers": {"35:3": _entry(beaten=True), "35:6": _entry(cls="BUG CATCHER", party=9)}}
    sm.merge_trainers(dst, src)
    t = dst["trainers"]
    assert set(t) == {"35:3", "35:6"} and "beaten" not in t["35:3"]
    # filling an empty field on an existing organic key
    src2 = {"trainers": {"35:3": _entry(prize=999)}}
    dst["trainers"]["35:3"]["prize"] = None
    sm.merge_trainers(dst, src2)
    assert dst["trainers"]["35:3"]["prize"] == 999 and dst["trainers"]["35:3"]["cls"] == "LASS"


def test_flag_bit_precedence_and_conflicts():
    dst = {"trainers": {"35:0": _entry(flag_bit=None)}}
    sm.merge_trainers(dst, {"trainers": {"35:0": _entry(flag_bit=[55123, 2])}})
    assert dst["trainers"]["35:0"]["flag_bit"] == [55123, 2]          # a set bit beats None
    sm.merge_trainers(dst, {"trainers": {"35:0": _entry(flag_bit=None)}})
    assert dst["trainers"]["35:0"]["flag_bit"] == [55123, 2]          # None never clears it
    sm.merge_trainers(dst, {"trainers": {"35:0": _entry(flag_bit=[55124, 2])}})
    assert dst["trainers"]["35:0"]["flag_bit"] == [55123, 2]          # dst wins the disagreement
    assert dst["trainers"]["35:0"]["conflict"] is True


def test_idempotent_and_malformed_input_ignored():
    src = {"trainers": {"35:3": _entry(flag_bit=[55123, 1]), "bad": "junk", "nul": None, 5: []}}
    dst = {}
    sm.merge_trainers(dst, src)
    once = dict(dst["trainers"])
    sm.merge_trainers(dst, src)
    sm.merge_trainers(dst, src)
    assert dst["trainers"] == once and "bad" not in once and "nul" not in once and 5 not in once
    sm.merge_trainers(dst, {"trainers": "not a dict"})
    assert dst["trainers"] == once


def test_synthetic_is_unconfirmed_and_never_overrides():
    dst = {"trainers": {"35:0": _entry(prize=210)}}
    sm.merge_trainers(dst, {"trainers": {"35:0": _entry(cls="X", prize=0, provenance="synthetic",
                                                       flag_bit=[55123, 0])}})
    assert dst["trainers"]["35:0"]["cls"] == "LASS" and dst["trainers"]["35:0"]["prize"] == 210
    assert "conflict" not in dst["trainers"]["35:0"]
    # a synthetic-born key is stored, but its flag_bit is only a hypothesis
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55123, 1], provenance="synthetic")}})
    e = dst["trainers"]["35:1"]
    assert e.get("flag_bit") is None and e["flag_bit_unconfirmed"] == [55123, 1]
    # 'unknown' provenance is also unconfirmed: same demotion
    sm.merge_trainers(dst, {"trainers": {"35:2": _entry(flag_bit=[55123, 2], provenance="unknown")}})
    assert dst["trainers"]["35:2"].get("flag_bit") is None


def test_organic_reproduction_promotes_the_unconfirmed_bit():
    dst = {"trainers": {}}
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55123, 1], provenance="synthetic")}})
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55123, 1], provenance="organic")}})
    e = dst["trainers"]["35:1"]
    assert e["flag_bit"] == [55123, 1] and "flag_bit_unconfirmed" not in e
    # an organic bit that disagrees with the hypothesis replaces it, no conflict recorded
    dst = {"trainers": {}}
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55199, 1], provenance="synthetic")}})
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55123, 1], provenance="organic")}})
    e = dst["trainers"]["35:1"]
    assert e["flag_bit"] == [55123, 1] and "conflict" not in e and "flag_bit_unconfirmed" not in e
    # the unconfirmed bit is never a flag_bit: sync_flags sees nothing to sync (no flag_bit key)
    assert "flag_bit" not in _unconfirmed_entry()


def _unconfirmed_entry():
    dst = {"trainers": {}}
    sm.merge_trainers(dst, {"trainers": {"35:1": _entry(flag_bit=[55123, 1], provenance="synthetic")}})
    return dst["trainers"]["35:1"]


def test_merge_memory_calls_merge_trainers():
    dst = {"maps": {}}
    sm.merge_memory(dst, {"maps": {}, "trainers": {"35:6": _entry(cls="BUG CATCHER", party=9, beaten=True)}})
    assert dst["trainers"]["35:6"]["cls"] == "BUG CATCHER" and "beaten" not in dst["trainers"]["35:6"]
    dst2 = {"maps": {}}
    sm.merge_memory(dst2, {"maps": {}})          # no trainers key: no empty table materialises
    assert "trainers" not in dst2
