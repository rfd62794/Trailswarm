from pokeagent.ramlab.gaps import summary, wram_gaps
from pokeagent.ramlab.labels import load_entries


def e(addr, size, name="x"):
    return {"name": name, "addr": f"0x{addr:04X}", "size": size, "region": "other", "verified": False}


def test_synthetic_gaps_exact():
    entries = [e(0xC010, 0x10), e(0xC020, 0x10), e(0xC018, 0x08)]      # overlap merges into C010-C02F
    gs = wram_gaps(entries)
    assert gs == [(0xC000, 0x10), (0xC030, 0xDFFF - 0xC030 + 1)]      # a gap at 0xC000 and one ending at 0xDFFF


def test_overlapping_entries_count_once():
    entries = [e(0xC000, 0x100), e(0xC080, 0x100)]
    assert wram_gaps(entries) == [(0xC180, 0xDFFF - 0xC180 + 1)]


def test_summary_on_committed_map():
    s = summary(load_entries())
    assert s["covered"] + s["unlabeled"] == s["total"] == 8192
    assert s["unlabeled"] == 758 and s["gaps"] == 110                 # measured 2026-11-12 (directive section 1)
    assert s["largest"][0] == (0xD430, 128)
    assert s["at_cap"] == 6
