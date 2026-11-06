"""Interaction classification from before/after RAM windows, the repeat-policy table and the heal decision."""
import pytest

from pokeagent.explorer import interaction_types as it
from pokeagent.explorer.interaction_policy import Need, decide, nearest_healer, needs_heal
from pokeagent.explorer.interaction_types import Effects, classify, read_effects, record_type


def win(money=3000, bag=(), party=((20, 20),), battle=0, mp=0x25, flags=0):
    w = bytearray(0x900)
    w[it.A_PARTY_N - it.BASE] = len(party)
    for i, (hp, mx) in enumerate(party):
        o = it.A_HP - it.BASE + 44 * i
        w[o:o + 2] = hp.to_bytes(2, "big")
        o = it.A_MAXHP - it.BASE + 44 * i
        w[o:o + 2] = mx.to_bytes(2, "big")
    w[it.A_BAG_N - it.BASE] = len(bag)
    for i, (item, q) in enumerate(bag):
        w[it.A_BAG - it.BASE + 2 * i:it.A_BAG - it.BASE + 2 * i + 2] = bytes([item, q])
    d = f"{money:06d}"
    w[it.A_MONEY - it.BASE:it.A_MONEY - it.BASE + 3] = bytes(int(d[i:i + 2], 16) for i in (0, 2, 4))
    w[it.A_BATTLE - it.BASE] = battle
    w[it.A_MAP - it.BASE] = mp
    w[it.A_FLAGS - it.BASE] = flags
    return bytes(w)


def kind(before, after, **kw):
    return classify(read_effects(before, after, **kw))[0]


def test_healer_party_hp_restored():
    assert kind(win(party=((3, 20), (10, 30))), win(party=((20, 20), (30, 30)))) == it.HEALER
    assert kind(win(party=((20, 20),)), win(party=((20, 20),)), texts=["Hi"]) == it.INFO  # nothing to heal: just talk


def test_shop_pc_trainer_vendor_giver():
    assert kind(win(), win(), menus=["BUY SELL QUIT"]) == it.SHOP
    assert kind(win(), win(), texts=["BCN turned on the PC."]) == it.PC
    assert kind(win(), win(battle=2)) == it.TRAINER
    assert kind(win(), win(battle=1)) == it.INFO  # a wild battle is not a trainer talk
    assert kind(win(money=3000), win(money=2500), texts=["Do you want a MAGIKARP for 500?"]) == it.VENDOR
    assert kind(win(), win(bag=[(0x46, 1)])) == it.GIVER
    assert kind(win(), win(), texts=["BCN got OAK PARCEL!"]) == it.GIVER


def test_story_blocker_sign_info():
    assert kind(win(), win(mp=0x26)) == it.STORY
    assert kind(win(flags=0), win(flags=1)) == it.STORY
    assert kind(win(), win(), repeat_same=True, pos_before=(1, 1), pos_after=(1, 2)) == it.BLOCKER
    assert kind(win(), win(), npc=False) == it.SIGN
    assert kind(win(), win(), texts=["The weather is nice"]) == it.INFO


def test_giver_beats_story_when_both_changed():
    assert kind(win(flags=0), win(flags=3, bag=[(0x46, 1)])) == it.GIVER


def test_votes_keep_the_majority_type():
    e = {}
    for fx in (Effects(), Effects(), Effects(battle=2)):
        record_type(e, fx)
    assert e["type"] == it.INFO and e["type_votes"] == {"info": 2, "trainer": 1} and e["type_conf"] == 0.67


def test_short_window_reads_as_unchanged():
    assert read_effects(b"", b"", texts=["x"]).texts == ["x"]


FULL, HURT = [(20, 20)], [(3, 20)]


@pytest.mark.parametrize("entry,need,talk", [
    (None, Need(), True),
    ({"type": "info", "pages": ["hi"]}, Need(), False),
    ({"type": "sign", "text": "hi"}, Need(), False),
    ({"type": "giver", "done": True}, Need(), False),
    ({"type": "giver", "gave": 0x46}, Need(bag_ids=frozenset({0x46})), False),
    ({"type": "giver"}, Need(), True),
    ({"type": "healer"}, Need(party=FULL), False),
    ({"type": "healer"}, Need(party=HURT), True),
    ({"type": "healer"}, Need(party=HURT, nearest_healer=False), False),
    ({"type": "shop"}, Need(), False),
    ({"type": "shop"}, Need(wants_item=True), True),
    ({"type": "vendor"}, Need(wants_item=True), True),
    ({"type": "trainer", "beaten": True}, Need(), False),
    ({"type": "trainer"}, Need(), True),
    ({"type": "blocker"}, Need(), False),
    ({"type": "blocker"}, Need(goal_changed=True), True),
    ({"type": "story"}, Need(), False),
])
def test_repeat_policy_table(entry, need, talk):
    got, rule = decide(entry, need)
    assert got is talk and rule


def test_heal_decision_needs_healing_and_nearest():
    assert needs_heal([(0, 20)]) and needs_heal([(9, 20)]) and not needs_heal([(10, 20)])
    assert nearest_healer({"mom": 40, "nurse": 12}) == "nurse" and nearest_healer({}) is None
