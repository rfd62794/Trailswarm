"""The live-position contract: atomic writes, tolerant reads, staleness and caching."""
import json
import os
from unittest.mock import patch

from pokeagent.mapview.live import STALE_S, LivePos, LiveStore, read_live, write_live


def rec(agent="a-1", **kw):
    r = {"schema": 1, "agent": agent, "run": "r1", "area": "1-1", "x": 4, "y": 9,
         "screen_x": 2, "screen_y": 3, "updated_at": 1000.0}
    r.update(kw)
    return r


def test_write_then_read_round_trip_atomically(tmp_path):
    write_live(tmp_path, rec())
    out = tmp_path / "live" / "a-1.json"
    assert out.is_file() and not (tmp_path / "live" / "a-1.json.tmp").exists()
    pos = read_live(out)
    assert pos == LivePos("a-1", "r1", "1-1", 4.0, 9.0, 2, 3, 1000.0)


def test_null_screen_position_round_trips(tmp_path):
    write_live(tmp_path, rec(screen_x=None, screen_y=None))
    pos = read_live(tmp_path / "live" / "a-1.json")
    assert pos.screen_x is None and pos.screen_y is None


def test_read_live_is_tolerant(tmp_path):
    p = tmp_path / "x.json"
    assert read_live(p) is None                                          # missing file
    p.write_text('{"schema": 1, "run"', encoding="utf-8")
    assert read_live(p) is None                                          # truncated JSON
    for bad in (rec(schema=2), rec(x="4"), rec(y=float("nan")),
                rec(updated_at=float("inf")), {"schema": 1, "agent": "a"}):
        p.write_text(json.dumps(bad), encoding="utf-8")
        assert read_live(p) is None, bad                                 # wrong schema/type/missing


def test_write_live_validates_and_never_raises(tmp_path):
    write_live(tmp_path, {"schema": 1, "agent": "a"})                    # missing keys: nothing written
    assert not (tmp_path / "live").exists() or not list((tmp_path / "live").glob("*.json"))
    write_live(tmp_path, rec(x="bad"))                                   # wrong type: nothing written
    assert not list((tmp_path / "live").glob("*.json"))
    with patch("pokeagent.mapview.live.os.replace", side_effect=OSError("ro")):
        write_live(tmp_path, rec())                                      # a failing write does not raise
    assert not list((tmp_path / "live").glob("*.tmp"))                   # tmp cleaned up


def test_store_refresh_picks_up_drops_and_stays_cached(tmp_path):
    store = LiveStore()
    assert store.refresh(tmp_path, 1000.0) is False                      # no live dir yet
    write_live(tmp_path, rec())
    assert store.refresh(tmp_path, 1000.0) is True                       # new file
    assert store.positions()["a-1"].x == 4.0
    parsed = store.parsed
    assert store.refresh(tmp_path, 1000.5) is False                      # same stamp: no re-parse
    assert store.parsed == parsed
    write_live(tmp_path, rec(x=7, updated_at=1000.5))                    # changed file
    assert store.refresh(tmp_path, 1000.5) is True
    assert store.parsed == parsed + 1 and store.positions()["a-1"].x == 7.0
    os.remove(tmp_path / "live" / "a-1.json")
    assert store.refresh(tmp_path, 1000.6) is True                       # vanished: forgotten
    assert store.positions() == {}


def test_store_treats_old_records_as_absent(tmp_path):
    store = LiveStore()
    write_live(tmp_path, rec(updated_at=100.0))
    assert store.refresh(tmp_path, 100.0 + STALE_S + 1) is False         # stale on arrival
    assert store.positions() == {}
    write_live(tmp_path, rec(updated_at=200.0))
    assert store.refresh(tmp_path, 200.0) is True                        # fresh again
    assert "a-1" in store.positions()


def test_store_skips_reparse_of_known_bad(tmp_path):
    store = LiveStore()
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "bad.json").write_text("{nope", encoding="utf-8")
    assert store.refresh(tmp_path, 1.0) is False                         # bad file: not a change
    parsed = store.parsed
    assert store.refresh(tmp_path, 2.0) is False and store.parsed == parsed
