"""Training controller slice 3 (Sustain): the heal rule's one owner, tick the sole train_route_live
writer, the hurt-no-potion start gate pinned, and the absorbed modules left with no importer. ROM-free."""
from __future__ import annotations

import inspect
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from pokeagent.explorer import grind_episode
from pokeagent.explorer.training_ctl import adapters, sustain
from pokeagent.explorer.training_ctl.controller import TrainingController
from test_grind_episode import PATCH_MAPS, make_ctx, make_ledger, use_ledger


def _ctx(grind=True):
    return SimpleNamespace(train_route_live=grind, view=SimpleNamespace(m=0x23), emu=object(), step=8, __dict__={})


def _pin_heal_reads(monkeypatch, *, needs=None, survives=True, fainted=False, topup=False):
    """heal_now fills the whole Sustain record: pin every read it makes on a synthetic ctx."""
    from pokeagent.explorer.behaviours import cave_topup
    monkeypatch.setattr(sustain, "party_needs_heal", needs if needs is not None else (lambda e, f: False))
    monkeypatch.setattr(sustain, "party_survives", lambda e, m: survives)
    monkeypatch.setattr(sustain, "read_party_view", lambda e: SimpleNamespace(any_fainted=fainted))
    monkeypatch.setattr(cave_topup, "wants_topup", lambda ctx: topup)


def test_heal_now_matches_the_old_grind_heal_verdicts(monkeypatch):
    """The three scenarios test_training_v2_slice3 put on grind_heal, now carried in one record."""
    _pin_heal_reads(monkeypatch, needs=lambda e, f: f >= 0.4)   # fighter ~30%: under 0.4, over PARTY_FLOOR
    h = sustain.heal_now(_ctx())
    assert h.grinding and h.weak is False and h.floor_heal is False   # survivable: stay in the grass
    _pin_heal_reads(monkeypatch, needs=lambda e, f: f >= 0.4, survives=False)
    h = sustain.heal_now(_ctx())
    assert h.weak is True and h.floor_heal is True                    # unsurvivable next fight: heal
    _pin_heal_reads(monkeypatch, survives=False, fainted=True)
    h = sustain.heal_now(_ctx())
    assert h.floor_heal is True and h.use_potion is False             # a faint needs the nurse, not a Potion


def test_goal_keys_feed_the_planner(monkeypatch):
    _pin_heal_reads(monkeypatch)
    monkeypatch.setattr(sustain, "heal_gate_hp", lambda e: (10, 30))
    ctx = _ctx()
    ctx.bandit = None
    keys = sustain.heal_now(ctx, {"deliver_parcel": True}).goal_keys()
    assert set(keys) == {"_survives", "_push_on"}                     # exactly the planner's two keys
    assert keys == {"_survives": True, "_push_on": False}             # bandit off: push_on False
    monkeypatch.setattr(sustain, "heal_push_on", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    assert sustain.heal_now(ctx).goal_keys() == {"_survives": True, "_push_on": False}   # no goals: never called


def test_leaving_and_to_grass(monkeypatch):
    assert sustain.leaving(("DOWN", "goal beat_misty: leaving the Pokecenter (4 steps)"), 0x40)
    assert not sustain.leaving(("UP", "HP 5/30: walking up to the nurse"), 0x40)
    assert not sustain.leaving(("DOWN", "goal x: leaving the Pokecenter (4 steps)"), 0x23)
    ctx = SimpleNamespace(mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()), emu=object(),
                          view=SimpleNamespace(m=0x40), facing="UP", __dict__={})
    monkeypatch.setattr(sustain, "heal_gate_hp", lambda e: (10, 30))
    monkeypatch.setattr(sustain, "party_survives", lambda e, m: True)
    monkeypatch.setattr(sustain.train_route, "step", lambda *a, **k: ("LEFT", "to the grass"))
    assert sustain.to_grass(ctx, ("UP", "keep"), (0x40, 4, 5), False) == ("UP", "keep")      # not live: untouched
    assert sustain.to_grass(ctx, None, (0x40, 4, 5), True) == ("LEFT", "to the grass")       # live, no plan: the walk
    assert sustain.to_grass(ctx, ("DOWN", "x: leaving the Pokecenter"), (0x40, 4, 5), True) == ("LEFT", "to the grass")
    monkeypatch.setattr(sustain.train_route, "step", lambda *a, **k: None)
    assert sustain.to_grass(ctx, ("UP", "keep"), (0x40, 4, 5), True) == ("UP", "keep")       # no route: press stays


def test_tick_is_the_sole_writer(monkeypatch):
    ctl = TrainingController()
    ctx = SimpleNamespace(train_route_live=False, step=10, train_need=0, goals=lambda: {})
    monkeypatch.setattr(adapters, "team_ready_live", lambda c: True)
    ctl.tick(ctx)
    assert ctx.train_route_live is True            # the stage verdict: live
    monkeypatch.setattr(adapters, "team_ready_live", lambda c: False)
    ctl.tick(ctx)
    assert ctx.train_route_live is False           # no stamp, not team_ready
    ctx.__dict__["grind_walk_step"] = ctx.step - 1
    ctl.tick(ctx)
    assert ctx.train_route_live is True            # a one-step-old grass-walk stamp keeps it live
    ctx.__dict__["grind_walk_step"] = ctx.step - 5
    ctl.tick(ctx)
    assert ctx.train_route_live is False           # a stale stamp does not
    ctx2 = SimpleNamespace(train_route_live=True, step=10, train_need=0, goals=lambda: {})   # no view
    monkeypatch.setattr(adapters, "team_ready_live", lambda c: c.view.m)   # blows up inside tick
    ctl.tick(ctx2)                                 # a read failure is logged, never raised ...
    assert ctx2.train_route_live is True           # ... and the flag keeps its last value


def test_engine_ticks_before_choose(tmp_path, monkeypatch):
    """choose() must see the flag tick computed at the top of THIS step, not last step's."""
    from pokeagent.explorer.engine import Engine
    from test_battle_types import make_ctx as real_ctx
    seen = []

    class Spy:
        def choose(self, ctx):
            seen.append(bool(ctx.train_route_live))
            return None

    monkeypatch.setattr(adapters, "team_ready_live", lambda c: True)
    ctx = real_ctx(tmp_path)
    ctx.refresh()
    Engine(ctx, selector=Spy()).step()
    assert seen == [True] and ctx.train_route_live is True


def test_an_episode_never_starts_hurt_with_no_potion(tmp_path, monkeypatch):
    """Pins the start gate that already runs _end_reason on the would-be episode: a member at 0 HP
    and an empty bag refuses to begin ('would end at once (hurt with no potion)')."""
    from pokeagent.explorer import retreat_risk as rr
    from test_after_victory import _mon
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), led)
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    monkeypatch.setattr(rr, "party_now", lambda emu: [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)])
    assert grind_episode.start(ctx) is False
    assert any("would end at once (hurt with no potion)" in t for t in ctx.logs)


def test_the_same_party_with_a_potion_is_not_refused_for_that_reason(tmp_path, monkeypatch):
    from pokeagent.explorer import retreat_risk as rr
    from test_after_victory import _mon
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), led)
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    monkeypatch.setattr(rr, "party_now", lambda emu: [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)])
    ctx.emu.set(0xD31D, 1)                          # one bag item ...
    ctx.emu.set(0xD31E, 0x14)                       # ... a POTION (item id 0x14), count 1
    ctx.emu.set(0xD31F, 1)
    assert grind_episode.start(ctx) is True         # the potion covers the hurt: the episode begins
    assert not any("hurt with no potion" in t for t in ctx.logs)


def test_hurt_no_potion_is_the_old_end_reason_expression(tmp_path, monkeypatch):
    """The moved check is the same boolean _end_reason computed inline (old grind_episode:231-234)."""
    from pokeagent.explorer import retreat_risk as rr
    from pokeagent.explorer.economy import heal_items
    from pokeagent.explorer.perceive import party_hp
    from pokeagent.goals import bag_contents
    from pokeagent.party_view import read_party_view
    from test_after_victory import _mon
    ctx = make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20))

    def old() -> bool:   # the pre-move expression, verbatim
        hp, mx = party_hp(ctx.emu)
        return bool((mx and not rr.party_survives(ctx.emu, ctx.view.m) or read_party_view(ctx.emu).any_fainted)
                    and not heal_items.heal_count(bag_contents(ctx.emu)))

    monkeypatch.setattr(rr, "party_now", lambda emu: [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)])
    assert sustain.hurt_no_potion(ctx) is True and old() is True            # hurt, no potion
    ctx.emu.set(0xD31D, 1); ctx.emu.set(0xD31E, 0x14); ctx.emu.set(0xD31F, 1)
    assert sustain.hurt_no_potion(ctx) is False and old() is False        # same hurt party + a Potion


def test_sustain_does_not_import_grind_episode():
    import_lines = [ln.strip() for ln in inspect.getsource(sustain).splitlines() if "import" in ln]
    assert import_lines and not any("grind_episode" in ln for ln in import_lines)


def test_no_src_module_imports_the_absorbed_modules():
    """grind_heal.py / after_heal.py stay in the tree until review deletes them; nothing under src/ imports them."""
    src = Path(sustain.__file__).resolve().parents[3]     # .../src
    offenders = []
    for f in src.rglob("*.py"):
        if f.name in ("grind_heal.py", "after_heal.py"):
            continue
        offenders += [f"{f.name}: {ln.strip()}" for ln in f.read_text(encoding="utf-8").splitlines()
                      if ("grind_heal" in ln or "after_heal" in ln) and "import" in ln]
    assert offenders == []


def test_fresh_process_imports_have_no_cycle():
    """Import cycles hide in a warm process: check the moved modules alone in a fresh interpreter."""
    codes = [
        "import pokeagent.explorer.training_ctl.sustain, pokeagent.explorer.behaviours.plan_goal, "
        "pokeagent.explorer.grind_episode, pokeagent.explorer.behaviours.retreat_heal, pokeagent.explorer.behaviours.frontier",
        "import pokeagent.explorer.grind_episode",
        "import pokeagent.explorer.training_ctl.sustain",
    ]
    for code in codes:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
