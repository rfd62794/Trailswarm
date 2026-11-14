"""The party-gate registry: a wild Harden-only KAKUNA violates wild-never-catch; a KAKUNA that knows POISON STING
(it evolved from a trained Weedle) does not; unknown team or kb data reads ``unknown``, never clean."""
from pokeagent import party_rules, statefp

HARDEN, POISON_STING, TACKLE = 106, 40, 33
KAKUNA, CHARMANDER = 113, 176
KB = {"name_of_internal": {"112": "WEEDLE", "113": "KAKUNA", "176": "CHARMANDER"},
      "moves": {"33": {"name": "TACKLE", "power": 35}, "40": {"name": "POISON STING", "power": 15},
                "106": {"name": "HARDEN", "power": 0}}}


def member(species, level, moves=()):
    return {"species": species, "level": level, "moves": list(moves), "hp": 9, "max_hp": 9, "ot_id": 1, "exp": 1}


def test_wild_harden_only_kakuna_violates_and_names_the_slot():
    fp = {"v": 1, "team": [member(CHARMANDER, 12, (TACKLE,)), member(KAKUNA, 4, (HARDEN, 0, 0, 0))]}
    vio = party_rules.violations(fp, KB)
    assert vio == ["wild KAKUNA L4 (Harden only) in slot 2"]
    assert party_rules.verdict(fp, KB) == "violation"
    assert party_rules.broken(fp, KB) == [("wild-never-catch", vio[0])]


def test_an_evolved_kakuna_with_poison_sting_is_clean():
    fp = {"v": 1, "team": [member(KAKUNA, 7, (HARDEN, POISON_STING))]}
    assert party_rules.violations(fp, KB) == [] and party_rules.verdict(fp, KB) == "clean"


def test_unknown_when_no_team_or_no_kb_tables():
    assert party_rules.verdict({"v": 1, "party": [[KAKUNA, 4, 5, 9]]}, KB) == "unknown"
    assert party_rules.verdict({"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]}, None) == "unknown"
    assert party_rules.verdict({"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]},
                               {"name_of_internal": {}, "moves": {}}) == "unknown"
    assert party_rules.violations({"v": 1}, KB) == []                          # unknown is not a violation


def test_recorded_violations_verdict_without_a_kb():
    fp = {"v": 1, "rule_violations": ["wild KAKUNA L4 (Harden only) in slot 1"]}
    assert party_rules.verdict(fp, None) == "violation"
    assert party_rules.violations(fp, None) == ["wild KAKUNA L4 (Harden only) in slot 1"]
    assert party_rules.broken(fp, KB)[0][0] == "recorded"


def test_gate_stamp_records_violations_and_logs(tmp_path):
    p = tmp_path / "q.state"
    p.write_bytes(b"x")
    fp = {"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]}
    logs = []
    found = party_rules.gate_stamp(fp, p, KB, log=logs.append)
    assert found == [("wild-never-catch", "wild KAKUNA L4 (Harden only) in slot 1")]
    assert statefp.read(p)["rule_violations"] == ["wild KAKUNA L4 (Harden only) in slot 1"]
    assert "state gate" in logs[0] and "wild-never-catch" in logs[0] and "q.state" in logs[0]
    clean = {"v": 1, "team": [member(CHARMANDER, 9, (TACKLE,))]}
    assert party_rules.gate_stamp(clean, p, KB, log=logs.append) == []
    assert "rule_violations" not in clean and len(logs) == 1


def test_quarantine_dest_never_overwrites_a_clean_checkpoint(tmp_path):
    dest = tmp_path / "to_pewter.state"
    dest.write_bytes(b"old")
    statefp.write(dest, {"v": 1, "team": [member(CHARMANDER, 9, (TACKLE,))]})    # the clean checkpoint on disk
    bad = {"v": 1, "team": [member(KAKUNA, 4, (HARDEN,))]}
    assert party_rules.quarantine_dest(bad, dest, KB).name == "to_pewter.quarantine.state"
    good = {"v": 1, "team": [member(CHARMANDER, 9, (TACKLE,))]}
    assert party_rules.quarantine_dest(good, dest, KB) == dest                   # a clean write replaces normally
    statefp.write(dest, bad)                                                    # the old one violates too: nothing to protect
    assert party_rules.quarantine_dest(bad, dest, KB) == dest
    statefp.sidecar(dest).unlink()                                              # no sidecar: cannot tell, write normally
    assert party_rules.quarantine_dest(bad, dest, KB) == dest
    assert party_rules.quarantine_dest(bad, tmp_path / "none.state", KB).name == "none.state"
