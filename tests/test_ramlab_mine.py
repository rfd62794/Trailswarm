from pokeagent.ramlab.kinds import kinds_of
from pokeagent.ramlab.labels import LabelIndex
from pokeagent.ramlab.mine import mine


def rec(ev, d, run="r1", step=1, vals=None, n=0):
    r = {"run": run, "step": step, "ev": ev, "map": 1, "x": 2, "y": 3, "vals": vals or {}, "d": d}
    if n:
        r["n"] = n
    return r


def synthetic():
    recs = []
    for i in range(6):          # battle_start: 0xD057 0->1, 0xD059 copies the enemy species, 0xD100 is random-ish
        recs.append(rec(["battle_start"], [[0xD057, 0, 1], [0xD059, 0, 20 + i], [0xD100, i, i + 7]], run=f"r{i % 2}", step=i,
                        vals={"enemy_species": 20 + i}))
    for i in range(20):         # plenty of other events that touch 0xD100 and 0xD362 constantly
        recs.append(rec(["step"], [[0xD100, i, i + 3], [0xD362, i, i + 1]], step=100 + i))
    for i in range(4):
        recs.append(rec(["money"], [[0xD347, 1, 2]], step=200 + i))
    return recs


def test_kinds():
    assert "inc1" in kinds_of(4, 5)
    assert "set_bit:3" in kinds_of(0b0001, 0b1001)
    assert "clear_bit:0" in kinds_of(0b0011, 0b0010)
    assert "copy:item" in kinds_of(0, 20, {"item": 20})
    assert "zero" in kinds_of(9, 0)


def test_miner_ranks_specific_consistent_changes_first():
    cands = mine(synthetic(), min_support=3)
    keys = [c.key() for c in cands]
    assert "battle_start@D057" in keys and "battle_start@D059" in keys
    assert "battle_start@D100" not in keys            # changes on other events just as often: not specific
    top = {c.key(): c for c in cands}
    assert top["battle_start@D059"].kind == "copy:enemy_species" and top["battle_start@D059"].consistency == 1.0
    assert top["battle_start@D057"].kind == "set_bit:0"
    assert top["battle_start@D057"].specificity == 1.0 and top["battle_start@D057"].runs == 2
    assert all(c.score > 0 for c in cands)
    assert cands == sorted(cands, key=lambda c: (-c.score, c.addr))


def test_min_support_filters():
    assert not [c for c in mine(synthetic(), min_support=7) if c.event == "battle_start"]


def test_truncated_records_do_not_dilute_rates():
    recs = [rec(["map_change"], [[0xD35E, 0, 5]], step=i) for i in range(3)]
    recs += [rec(["map_change"], [[0xC000, 1, 2]], step=10 + i, n=900) for i in range(10)]   # hide everything else
    c = {x.key(): x for x in mine(recs, min_support=3)}["map_change@D35E"]
    assert c.rate == 1.0


ENTRIES = [
    {"name": "wPlayerMoney", "addr": "0xD347", "size": 3, "region": "items", "verified": True},
    {"name": "wIsInBattle", "addr": "0xD057", "size": 1, "region": "battle", "verified": True},
    {"name": "wCurOpponent", "addr": "0xD059", "size": 1, "region": "battle", "verified": False},
    {"name": "wTileMap", "addr": "0xC3A0", "size": 360, "region": "text", "verified": False},
    {"name": "wUnusedD000", "addr": "0xD000", "size": 4, "region": "other", "verified": False},
]


def test_label_join():
    idx = LabelIndex(ENTRIES)
    assert idx.join("money", 0xD348)[0] == "confirms" and idx.join("money", 0xD348)[1].name == "wPlayerMoney"
    assert idx.join("battle_start", 0xD059)[0] == "confirms"
    assert idx.join("map_change", 0xD059)[0] == "labelled"             # a label, but money should not touch it
    assert idx.join("battle_start", 0xD123) == ("new", None)      # no label
    assert idx.join("battle_start", 0xD001)[0] == "new"           # unused region counts as unknown
    assert idx.join("text_open", 0xC400)[0] == "confirms"


def test_stack_is_not_a_finding():
    idx = LabelIndex(ENTRIES + [{"name": "wStack", "addr": "0xDFFF", "size": 1, "region": "other", "verified": False}])
    assert idx.join("text_close", 0xDFF8)[0] == "stack"
    assert idx.join("battle_start", 0xC057)[0] == "new"          # no label -> new
