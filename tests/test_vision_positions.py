"""PositionLog: one contract line per sampled frame, byte cap sets capped, stationary entities repeat."""
from __future__ import annotations

import json

from pokeagent.vision.positions import PositionLog


def test_one_line_per_call_with_contract_keys(tmp_path):
    log = PositionLog(tmp_path)
    log.append(32, "run", "map-5", (5, 6), [["slot1", 13, 6, 6, 0xFE]])
    log.append(40, "run", "map-5", (5, 6), [["slot1", 13, 6, 6, 0xFE]])   # stationary, still logged
    log.close()
    lines = [json.loads(ln) for ln in (tmp_path / "positions.jsonl").read_text().splitlines()]
    assert lines == [{"f": 32, "run": "run", "area": "map-5", "player": [5, 6],
                      "ents": [["slot1", 13, 6, 6, 254]]},
                     {"f": 40, "run": "run", "area": "map-5", "player": [5, 6],
                      "ents": [["slot1", 13, 6, 6, 254]]}]


def test_cap_stops_appending_and_sets_capped(tmp_path):
    log = PositionLog(tmp_path, max_bytes=90)
    for i in range(10):
        log.append(i, "run", "map-5", (5, 6), [["slot1", 13, 6, 6, 0]])
    log.close()
    assert log.capped
    n = len((tmp_path / "positions.jsonl").read_text().splitlines())
    assert 0 < n < 10
    log2 = PositionLog(tmp_path, max_bytes=90)          # a capped file stays capped on reopen
    assert log2.capped
    log2.close()


def test_existing_file_continues_appending(tmp_path):
    log = PositionLog(tmp_path)
    log.append(1, "run", "map-1", (0, 0), [])
    log.close()
    log2 = PositionLog(tmp_path)
    log2.append(2, "run", "map-1", (0, 0), [])
    log2.close()
    assert len((tmp_path / "positions.jsonl").read_text().splitlines()) == 2
