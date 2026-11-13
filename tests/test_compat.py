"""Compat check: ledge classifier, map comparison, address comparison, verdicts, CLI exit codes, ROM-check helpers."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pokeagent.compat import build_report, compare_addresses, compare_memory
from pokeagent.compat.ledges import classify_wall, opposite, parse_edge
from pokeagent.compat.rom_check import compare_symbol_counts, symbol_operand_counts, wild_overlay
from pokeagent.compat.thresholds import PROPOSED, evaluate

FIX = Path(__file__).parent / "fixtures" / "compat"
ROOT = Path(__file__).resolve().parents[1]


def test_classify_wall():
    m = {"jumps": {"5,26,DOWN": [5, 28]}}
    assert classify_wall(m, "5,28,UP") == "ledge_exact"
    assert classify_wall(m, "9,28,UP") == "ledge_row"
    assert classify_wall(m, "9,29,UP") == "plain" and classify_wall({}, "1,1,UP") == "plain"
    assert opposite("LEFT") == "RIGHT" and parse_edge("1,2,UP") == (1, 2, "UP")
    for bad in ("1,2", "a,b,UP", "1,2,JUMP"):
        with pytest.raises(ValueError):
            parse_edge(bad)


def _doc(visited, blocked=(), warps=None, npcs=None, jumps=None):
    return {"maps": {"1": {"visited": {t: 1 for t in visited}, "blocked": list(blocked),
                           "warps": warps or {}, "npcs": npcs or {}, "jumps": jumps or {}}}}


def test_compare_memory_counts_and_wall_split():
    base = _doc(["0,0", "0,1"], blocked=["0,1,UP", "5,28,UP", "9,9,UP", "bad"], warps={"1,1,UP": [2, 0, 0]},
                jumps={"5,26,DOWN": [5, 28]}, npcs={"n": {"pic": 3, "moves": False, "last": [1, 1]}})
    cand = _doc(["0,0", "0,1", "5,28", "5,27", "9,9", "9,8", "7,7"], warps={"1,1,UP": [3, 0, 0], "2,2,UP": [1, 1, 1]},
                npcs={"n": {"pic": 3, "moves": False, "last": [1, 1]}})
    t = compare_memory(base, cand)["totals"]
    assert (t["tiles"], t["overlap"], t["candidate_only"]) == (7, 2, 5)
    assert (t["warps_common"], t["warps_different"], t["warps_candidate_only"]) == (1, 1, 1)
    assert (t["npc_candidate"], t["npc_match"]) == (1, 1)
    assert (t["walls_suspect"], t["walls_ledge_exact"], t["walls_plain"], t["walls_malformed"]) == (3, 1, 2, 1)
    assert compare_memory({"maps": {}}, {"maps": {}})["shared_maps"] == 0


def test_compare_addresses():
    b = [{"name": "a", "addr": "0x1", "verified": True}, {"name": "b", "addr": "0x2", "verified": True},
         {"name": "c", "addr": "0x3"}]
    c = [{"name": "a", "addr": "0x1"}, {"name": "b", "addr": "0x9"}, {"name": "z", "addr": "0x4"}]
    r = compare_addresses(b, c)
    assert (r["in_both"], r["only_baseline"], r["only_candidate"], r["addr_different"]) == (2, 1, 1, 1)
    assert (r["verified_in_baseline"], r["verified_present"], r["verified_addr_different"]) == (2, 2, 1)


def _good():
    return {"shared_maps": 15, "totals": {"tiles": 1000, "overlap": 990, "warps_common": 20, "warps_different": 0,
                                           "npc_candidate": 30, "npc_match": 30, "baseline_walls": 1000, "unexplained": 5}}


def test_verdicts():
    assert evaluate(_good(), None)[1] == "pass"
    cases = {"tile_overlap": ("overlap", 100), "warps_different": ("warps_different", 1),
             "npc_match": ("npc_match", 5), "wall_unexplained": ("unexplained", 500)}
    for rule, (k, v) in cases.items():
        m = _good()
        m["totals"][k] = v
        rules, verdict = evaluate(m, None)
        assert verdict == "fail" and any(r["rule"].startswith(rule) and r["status"] == "fail" for r in rules), rule
    for edit in (lambda m: m.update(shared_maps=3), lambda m: m["totals"].update(tiles=100, overlap=100),
                 lambda m: m["totals"].update(warps_common=2), lambda m: m["totals"].update(npc_candidate=3, npc_match=3)):
        m = _good()
        edit(m)
        assert evaluate(m, None)[1] == "insufficient"
    m = _good()
    m["totals"].update(baseline_walls=0, unexplained=0)  # a zero denominator never passes
    assert evaluate(m, None)[1] == "insufficient"
    addr = {"verified_addr_different": 1, "verified_in_baseline": 10, "verified_present": 10}
    assert evaluate(_good(), addr)[1] == "fail"
    assert evaluate(_good(), {**addr, "verified_addr_different": 0})[1] == "pass"
    assert PROPOSED["tile_overlap_min"] == 0.95


def test_threshold_override_is_recorded():
    m = _good()
    m["totals"]["unexplained"] = 500
    rep = build_report({"maps": {}}, {"maps": {}}, overrides={"min_shared_maps": 0})
    assert rep["thresholds_overridden"] == ["min_shared_maps"] and rep["thresholds_status"] == "proposed"
    assert evaluate(m, None, {"wall_unexplained_max": 0.9})[1] == "pass"


def _run(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "game_compat.py"), *args], capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""})


def test_cli_pass_fixtures_and_exit_codes(tmp_path):
    base, cand = FIX / "baseline_maps.json", FIX / "candidate_maps.json"
    out = tmp_path / "r.json"
    r = _run("--baseline", str(base), "--candidate", str(cand), "--out", str(out))
    assert r.returncode == 0 and r.stdout.startswith("verdict: pass") and "proposals" in r.stdout
    rep = json.loads(out.read_text())
    assert {"schema", "generated", "baseline_name", "candidate_name", "inputs", "memory", "addresses",
            "thresholds_status", "rules", "verdict"} <= set(rep) and rep["addresses"] == "skipped"
    small = tmp_path / "small.json"
    small.write_text(json.dumps({"maps": {}}))
    assert _run("--baseline", str(base), "--candidate", str(small)).returncode == 3
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    r = _run("--baseline", str(base), "--candidate", str(bad))
    assert r.returncode == 2 and r.stdout.startswith("error:") and "Traceback" not in r.stderr
    assert _run("--baseline", str(base), "--candidate", str(base), "--baseline-addresses", str(base)).returncode == 2
    worse = json.loads(cand.read_text())
    for m in worse["maps"].values():
        m["warps"] = {k: [99, 0, 0] for k in m["warps"]}
    wp = tmp_path / "worse.json"
    wp.write_text(json.dumps(worse))
    assert _run("--baseline", str(base), "--candidate", str(wp)).returncode == 1


def test_symbol_operand_counts_and_wild_overlay():
    rom = bytes([0xFA, 0x5E, 0xD3, 0, 0xEA, 0x5E, 0xD3, 0x00, 0x21, 0x57, 0xD0])
    counts = symbol_operand_counts(rom, {"wCurMap": 0xD35E, "wIsInBattle": 0xD057, "none": 0xD999})
    assert counts == {"wCurMap": 2, "wIsInBattle": 1, "none": 0}
    ok = compare_symbol_counts(counts, dict(counts))
    assert ok["mismatched"] == {} and ok["unreferenced"] == ["none"]
    assert compare_symbol_counts(counts, {**counts, "wCurMap": 9})["mismatched"] == {"wCurMap": (2, 9)}
    red = {12: {"grass_rate": 25, "grass": [[3, "RATTATA"]]}, 13: {"grass_rate": 5}}
    blue = {12: {"grass_rate": 25, "grass": [[3, "RATTATA"]]}, 13: {"grass_rate": 5, "grass": [[4, "ODDISH"]]}}
    assert wild_overlay(red, blue) == {"wild_by_map": {"13": blue[13]}}
    assert wild_overlay(red, red) == {}


def _synthetic_rom(blocks_at: int, blocks: bytes = bytes(range(6))) -> bytes:
    """A 64 KiB ROM with one sane map (id 0, 2x3 blocks, no connections/warps/signs/objects)."""
    from pokeagent.atlas.rom_maps import BANKS, PTRS
    rom = bytearray(0x10000)
    rom[BANKS] = 1
    hdr, obj = 0x4100, 0x4200
    rom[PTRS:PTRS + 2] = hdr.to_bytes(2, "little")
    rom[hdr:hdr + 9] = bytes([0, 2, 3]) + blocks_at.to_bytes(2, "little") + bytes(4)  # tileset,h,w,blocks,text,script
    rom[hdr + 10:hdr + 12] = obj.to_bytes(2, "little")
    rom[blocks_at:blocks_at + len(blocks)] = blocks
    return bytes(rom)


def test_compare_headers_pointer_shift_is_not_a_difference():
    from pokeagent.compat.rom_check import compare_headers
    h = compare_headers(_synthetic_rom(0x5000), _synthetic_rom(0x5001))
    assert h["maps_red"] == h["maps_blue"] == 1
    assert h["different"] == [] and h["block_differences"] == [] and h["pointer_shifts"] == 1


def test_compare_headers_reports_real_block_content_difference():
    from pokeagent.compat.rom_check import compare_headers
    h = compare_headers(_synthetic_rom(0x5000), _synthetic_rom(0x5001, bytes([9] * 6)))
    assert h["block_differences"] == [0] and h["pointer_shifts"] == 0 and h["different"] == []
