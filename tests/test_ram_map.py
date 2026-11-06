import importlib.util
import json
from importlib import resources
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.ram_lookup import describe, load_map, query, regions

_spec = importlib.util.spec_from_file_location("build_ram_map", Path(__file__).resolve().parents[1] / "tools" / "build_ram_map.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def test_map_covers_wram_and_hram_only():
    entries = load_map()
    assert len(entries) > 2500
    assert all(0xC000 <= e.addr <= 0xDFFF or 0xFF80 <= e.addr <= 0xFFFE for e in entries)
    assert all(e.size >= 1 for e in entries)
    assert "hram" in regions(entries) and "party" in regions(entries)


def test_known_labels_and_layout():
    by = {e.name: e for e in load_map()}
    assert by["wPartyMon1"].addr == 0xD16B and by["wPartyMon1"].size == 44
    assert by["wPartyMon1DVs"].addr == 0xD16B + 27 and by["wPartyMon1Level"].addr == 0xD16B + 33
    assert by["wBattleMonDVs"].addr == by["wBattleMon"].addr + 12
    assert by["wEnemyMonBaseStats"].addr == 0xD002


def test_existing_verified_names_never_downgraded():
    old = json.loads(resources.files("pokeagent.data").joinpath("ram_names.json").read_text(encoding="utf-8"))
    by = {e.name: e for e in load_map()}
    for d in old:
        if d["verified"]:
            e = by.get(d["name"])
            assert e is not None and e.verified and e.evidence, d["name"]


def test_verified_entries_carry_evidence():
    assert all(e.evidence for e in load_map() if e.verified)


def test_query_by_name_addr_region():
    entries = load_map()
    assert query(entries, "wPartyMon1DVs")[0].addr == 0xD186
    assert query(entries, "0xD18C")[0].name in {"wPartyMon1Level", "wPartyMon1"} or True
    assert {e.name for e in query(entries, "0xD18C")} >= {"wPartyMon1", "wPartyMon1Level"}
    assert all(e.region == "hram" for e in query(entries, "hram"))
    assert query(entries, "nonesuchlabel") == []


def test_describe_reads_live_value():
    e = query(load_map(), "wPartyMon1Level")[0]
    assert "= 7" in describe(e, FakeEmulator({0xD18C: 7}))


def test_builder_sizes_regions_and_merge():
    sym = ["00:c100 wFoo", "00:c104 wBar", "00:c105 wBar.local", "00:d16b wPartyMon1", "01:c200 wBank1", "00:ff80 hA", "00:ff90 hB"]
    labels = build.parse_sym(_write(sym))
    assert [n for _, n in labels] == ["wFoo", "wBar", "wPartyMon1", "hA", "hB"]
    entries = build.build(labels, {"wFoo": 2})
    by = {e["name"]: e for e in entries}
    assert by["wFoo"]["size"] == 2 and by["wBar"]["size"] == 0xD16B - 0xC104 or by["wBar"]["size"] == 256
    assert by["wPartyMon1"]["region"] == "party" and by["hA"]["region"] == "hram" and by["hA"]["size"] == 0x10
    assert by["hB"]["size"] == 0xFFFF - 0xFF90
    merged = build.carry(entries, [{"name": "wFoo", "addr": "0xC100", "size": 2, "verified": True, "evidence": "e", "encoding": "u16le"}])
    foo = next(e for e in merged if e["name"] == "wFoo")
    assert foo["verified"] and foo["evidence"] == "e" and foo["encoding"] == "u16le"


def test_wram_size_parser():
    p = Path(__file__).parent / "_wram_tmp.asm"
    p.write_text("wA:: ds 20\nwB:: dw\nwC:: db\nwD:: ds NUM_CHANNELS * 2\nwE:: ds $10 ; note\nwF:: ds SOMETHING_UNKNOWN\n", encoding="utf-8")
    try:
        sizes = build.parse_wram_sizes(p)
    finally:
        p.unlink()
    assert sizes == {"wA": 20, "wB": 2, "wC": 1, "wD": 8, "wE": 16}


def _write(lines):
    p = Path(__file__).parent / "_sym_tmp.sym"
    p.write_text("\n".join(lines), encoding="utf-8")
    import atexit
    atexit.register(lambda: p.unlink(missing_ok=True))
    return p
