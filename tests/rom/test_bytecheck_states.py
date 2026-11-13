"""Do committed save states hold ROM bytes? Builds an index from the real ROM (controller/laptop only)."""
import pytest

from rom_helpers import ROM, STATES


def test_states_not_leaking_rom_bytes():
    if not ROM.exists():
        pytest.skip("needs roms/Pokemon Red.gb (gitignored; the controller runs these)")
    states = sorted(STATES.glob("*.state"))
    if not states:
        pytest.skip("no tests/fixtures/rom_states/*.state")
    from pokeagent.bytecheck import policy
    from pokeagent.bytecheck.fingerprint import build_index
    from pokeagent.bytecheck.scan import scan_file
    idx = build_index(ROM.read_bytes())
    for s in states:
        res = scan_file(s, idx)
        v = policy.verdict(res, "state")
        print(f"{s.name}: {v} windows={res.matched_windows} cov={res.coverage:.4%} run={res.longest_run}")
        assert v in (policy.CLEAN, policy.SUSPECT), f"{s.name}: {res.to_dict()}"
