"""retalk_veto and box_settle: no A at a memorised worthless spot, no A at an empty box."""
from types import SimpleNamespace as NS

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import interaction_types as it
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.behaviours.box_settle import BoxSettle, PostTalkSettle
from pokeagent.explorer.retalk_veto import veto


class Mem:
    def __init__(self, entry):
        self.entry = entry
        self.data = {}

    def npc_at(self, m, x, y):
        return None

    def m(self, m):
        return {"interactions": {"3,4,UP": self.entry}}


def ctx_for(entry, hp=(20, 20)):
    emu = FakeEmulator({it.A_PARTY_N: 1, it.A_HP: hp[0] >> 8, it.A_HP + 1: hp[0] & 255,
                        it.A_MAXHP: hp[1] >> 8, it.A_MAXHP + 1: hp[1] & 255})
    return NS(emu=emu, mem=Mem(entry), facing="UP", proc=None, view=NS(m=1, x=3, y=4, box=False, battling=False),
              pos_hist=[], goals=lambda: {}, goto=None, center_intent=None, box_empty_waits=0, box_empty_since=-1, frame=0, talk_closed_frame=-1, post_talk_waits=0)


def test_memorised_info_is_vetoed_but_a_hurt_party_lets_the_press_through():
    info = {"type": "info", "pages": ["hello"], "count": 2}
    assert veto(ctx_for(info), Decision("A", "x")) is not None
    assert veto(ctx_for(info, hp=(2, 20)), Decision("A", "x")) is None
    assert veto(ctx_for(info), Decision("UP", "x")) is None


def test_unknown_or_unvetoable_spots_are_never_vetoed():
    assert veto(ctx_for(None), Decision("A", "x")) is None
    assert veto(ctx_for({"type": "shop"}), Decision("A", "x")) is None
    assert veto(ctx_for({"type": "giver"}), Decision("A", "x")) is None  # not given yet: talk once


def test_box_settle_waits_on_an_empty_box_then_gives_up():
    c = ctx_for(None)
    c.view = NS(box=True, lines=[], battling=False)
    b = BoxSettle()
    assert b.applies(c) and b.step(c).button == ""
    c.view.lines = ["Hello"]
    assert not b.applies(c) and c.box_empty_waits == 0
    c.view.lines = []
    for _ in range(60):
        c.box_empty_waits += 1
    assert not b.applies(c)  # bounded: a wordless frame can never stall the agent


def test_post_talk_settle_waits_a_few_frames_after_a_box_closes():
    c = ctx_for(None)
    c.talk_closed_frame, c.frame = 100, 105
    p = PostTalkSettle()
    assert p.applies(c) and p.step(c).button == ""
    c.frame = 200
    assert not p.applies(c)


def test_a_goto_target_or_changed_goal_lets_the_spot_be_read_again():
    info = {"type": "info", "pages": ["hello"], "count": 2, "goal": "potion"}
    c = ctx_for(info)
    assert veto(c, Decision("A", "x")) is not None
    c.goto = [1, 3, 4]
    assert veto(c, Decision("A", "x")) is None


def test_readiness_mash_never_talks_to_something_in_front():
    c = ctx_for(None)
    c.mem.npc_at = lambda m, x, y: {"pic": 61}
    assert veto(c, Decision("A", "mash", behaviour="readiness")) is not None
    assert veto(c, Decision("A", "advance", behaviour="plan_goal")) is None  # the planner may talk on purpose
