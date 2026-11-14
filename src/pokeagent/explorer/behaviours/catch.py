"""catch: a wild species we do not own -> the catch policy's step (weaken / status / switch / throw).

The policy (knowledge.catch_policy) decides through ``ctx.catch_hint``: a status_move or damage_move is
picked by battle_moves, a switch is pressed through switch_out's helper, a throw uses ITEM -> the hinted
ball. The original rule (a POKE BALL at <=35% HP) stays as the fallback for when there is no ROM data to
decide with (catch_hint is None), and attempts are recorded to learn the odds.
"""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.behaviours.battle_run import cave_catch_allowed
from pokeagent.explorer.behaviours.item_use import item_list_open, item_step
from pokeagent.explorer.behaviours.switch_out import MAX_PRESSES, switch_press
from pokeagent.explorer.catch_list import catch_wanted, dex_owned_count, upcoming_needs
from pokeagent.explorer.party_menu import MENU_ITEM, screen_lines
from pokeagent.explorer.perceive import frame_lines
from pokeagent.explorer.training_ctl import roster
from pokeagent.goals import bag_contents
from pokeagent.knowledge.catch_math import BALLS, FALLBACK_PRICE, status_kind
from pokeagent.knowledge.catch_plan import TEAM_SIZE
from pokeagent.knowledge.catch_policy import decide, may_throw_ctx
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party, species_row, trainer_mon
from pokeagent.knowledge import team_plan
from pokeagent.ramstructs import active_slot, read_enemy_mon, read_party

POKE_BALL = 0x04
CATCH_BAG_PRESSES = 60   # bag presses without a throw landing before the catch sequence is abandoned (a throw is about 4 presses plus the scroll depth)
BALL_NAME = {"POKE": "POKe BALL", "GREAT": "GREAT BALL", "ULTRA": "ULTRA BALL", "MASTER": "MASTER BALL"}


def full_party_slot(ctx: ExplorerContext, party) -> int | None:
    """The member a full party marks for deposit when a wanted catch lands, else None: the lowest-value
    member (its level when no member scoring is at hand), never the trainee, never a learner the run
    still needs. The caught mon goes to the PC box; the mark is what the deposit prompt answers
    while this battle lasts (``release_pending`` is cleared when the fight ends)."""
    if len(party or ()) < TEAM_SIZE:
        return None
    from pokeagent.explorer.catch_list import HM_MOVE, NEVER_CATCH, hm_table, upcoming_needs
    needs, hm = upcoming_needs(ctx.goals()), hm_table()
    protected = {i for i, c in enumerate(party)
                 if any(n in HM_MOVE and (c.name in hm.get(n, ()) or HM_MOVE[n] in c.moves) for n in needs)}
    t = roster.trainee_slot(ctx)
    if t is not None:
        protected.add(t)
    # A NEVER_CATCH member (a wild KAKUNA knows only Harden; Robert 2026-11-14) scores below every
    # other member so it is the deposit pick - never past a protected slot, so a Kakuna that is the
    # current trainee or a needed HM learner is still kept.
    values = [-1 if getattr(c, "name", None) in NEVER_CATCH else c.level for c in party]
    return team_plan.release_candidate(party, protected=protected, values=values)


def _policy_hint(ctx: ExplorerContext, sp_name: str, e_lvl: int, e_hp: int, e_max: int,
                 bag: dict[int, int], turn: int):
    """The catch policy's CatchStep for this step, or None when there is no ROM data to decide with."""
    party = our_party(ctx.emu)
    wild = trainer_mon(sp_name, e_lvl)
    if not party or wild is None:
        return None
    pos = active_slot(ctx.emu)  # wBattleMon.party_pos goes stale after a forced post-faint switch
    lead = pos if pos is not None and 0 <= pos < len(party) else 0
    active = party[lead]
    raw = read_party(ctx.emu)   # current HP per slot (Combatant.hp is the max); only trusted when the slots line up
    party_hp = [(m.hp, m.max_hp) for m in raw] if len(raw) == len(party) else None
    items = (ROM_KB or {}).get("items", {})
    price = {name: int((items.get(str(i)) or {}).get("price") or FALLBACK_PRICE.get(name, 200))
             for name, i in BALLS.items()}
    rate = int((species_row(sp_name) or {}).get("catch_rate") or 0)
    return decide(active, party, replace(wild, hp=max(1, e_hp)), e_hp, e_max,
                  status_kind(read_enemy_mon(ctx.emu).status), rate,
                  {name: bag.get(i, 0) for name, i in BALLS.items()}, price,
                  {(a, d): e for a, d, e in table(None, "type_chart")}, table(None, "moves"), turn=turn,
                  kind=ctx.bv.kind, trainer_npc=ctx.trainer_npc,
                  battle_log_kind=(ctx.battle_log or {}).get("kind"), lead=lead, party_hp=party_hp)


def _attempt(ctx: ExplorerContext, species: int, e_lvl: int, ratio: float, dex_no: int, ball: str | None) -> dict:
    """The one catch_attempt record per (battle, species): refreshed in place so its ``step`` (the turn signature's
    input) stays put, and carrying the bag-press count the cap and Battle's item_list_close yield read."""
    ca = ctx.catch_attempt
    if not ca or ca.get("battle") != ctx.battles or ca.get("species") != species:
        ca = ctx.catch_attempt = {"species": species, "level": e_lvl, "step": ctx.step, "dex": dex_no,
                                  "battle": ctx.battles, "presses": 0, "last": ctx.step}
    ca["hp_pct"] = round(ratio, 2)
    if ball is not None:
        ca["ball"] = ball
    return ca


def _bag_press(ctx: ExplorerContext, ca: dict, dec: Decision, key, sp_name) -> Decision:
    """Count a bag press; a throw landing resets the count; too many presses without one abandons the sequence."""
    ca["last"] = ctx.step
    ca["presses"] = 0 if dec.rule == "item_use" else ca["presses"] + 1
    if ca["presses"] > CATCH_BAG_PRESSES:
        ctx.catch_switch = (key, 10**6)   # the existing give-up marker: no new hint for the rest of this battle
        ctx.catch_mode, ctx.catch_hint = False, None
        ctx.log(f"[catch: bag sequence gave up after {CATCH_BAG_PRESSES} presses without a throw on {sp_name}; fighting on]", "res")
        return Decision("B", "catch_bag_failed", "catch bag sequence abandoned: backing out of the menu")
    return dec


class Catch(BehaviourBase):
    name = "catch"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling and ctx.bv is not None  # also resets catch_mode on every fight step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        lines_now = ctx.view.lines
        bv = ctx.bv
        kind, species, e_lvl, run_line = bv.kind, bv.species, bv.e_lvl, bv.run_line
        # --- catching: a wild species we do not own yet, with a ball in the bag -> the catch policy decides;
        #     the throw itself is ITEM -> the hinted ball. Attempts and results are recorded to learn catch odds.
        bag = bag_contents(ctx.emu)
        balls = sum(bag.get(i, 0) for i in BALLS.values())
        dex_no = int((ROM_KB or {}).get("dex_of_internal", {}).get(str(species), 0) or 0)
        owned = bool(dex_no) and bool(ctx.emu.read(0xD2F7 + (dex_no - 1) // 8) >> ((dex_no - 1) % 8) & 1)
        e_hp, e_max = ((ctx.emu.read(0xCFE6) << 8) | ctx.emu.read(0xCFE7)), ((ctx.emu.read(0xCFF4) << 8) | ctx.emu.read(0xCFF5))
        want = sp_name = None
        if kind == 1 and balls and dex_no and e_max and cave_catch_allowed(ctx, species):
            sp_name = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), str(species))
            key = (ctx.battles, species)
            if ctx.catch_want[0] != key:  # decided once per fight: the party read is not free
                why = catch_wanted(sp_name, our_party(ctx.emu), dex_owned_count(ctx.emu), upcoming_needs(ctx.goals()),
                                   owned=owned, wants=ctx.team_wants)
                ctx.catch_want = (key, why)
                ctx.log(f"[catch: {'wanted' if why else 'skipping'} {sp_name}: {why or 'not on the need-list'}]", "res")
            want = ctx.catch_want[1]
        # Party full: throw only when the plan marks a member for deposit (a live release_pending
        # makes the deposit prompt answer YES); otherwise the catch is skipped with "party full".
        release_slot = None
        if want and len(read_party(ctx.emu)) >= TEAM_SIZE:
            st = team_plan.of(ctx)
            marked = st.get("release_mark")   # settled once per battle: the party read is not free
            if marked and marked[0] == ctx.battles:
                release_slot = marked[1]
            else:
                release_slot = full_party_slot(ctx, our_party(ctx.emu))
                st["release_mark"] = (ctx.battles, release_slot)
            if release_slot is None:
                if ctx.catch_skip_logged != ctx.catch_want[0]:
                    ctx.catch_skip_logged = ctx.catch_want[0]
                    ctx.log(f"[catch: skipping {sp_name}: party full]", "res")
                ctx.catch_mode, ctx.catch_hint = False, None   # a stale weaken-only mode must not outlive this battle
                return None
            st["release_pending"] = {"species": sp_name, "slot": release_slot, "battle": ctx.battles}
            ctx.log(f"[catch: party full - slot {release_slot + 1} marked for deposit for {sp_name}]", "res")
        gave_up = ctx.catch_switch[0] == ctx.catch_want[0] and ctx.catch_switch[1] > MAX_PRESSES
        if gave_up or not (want and balls and dex_no and e_max and may_throw_ctx(ctx)
                           and (not owned or want.startswith(("can learn", "planned")))):
            ctx.catch_mode = False
            ctx.catch_hint = None
            return None
        ratio = e_hp / e_max
        # A policy turn = one change of the situation signature (a hit landed, a status stuck, a switch or
        # a throw went through, our move was chosen); menu-walking steps between actions are not turns.
        enemy = read_enemy_mon(ctx.emu)
        key = ctx.catch_want[0]
        sig = (e_hp, enemy.status, bv.my_sp, balls, (ctx.pending_move or {}).get("step"), (ctx.catch_attempt or {}).get("step"))
        prev = ctx.catch_turns
        turn = prev[2] if prev[0] == key else 0
        if prev[0] != key or prev[1] != sig:
            turn += 1
        ctx.catch_turns = (key, sig, turn)
        hint = _policy_hint(ctx, sp_name, e_lvl, e_hp, e_max, bag, turn)
        ctx.catch_hint = hint
        ctx.catch_mode = hint is None or hint.kind != "skip"  # a skip means fight it out normally
        if hint is not None and hint.kind == "skip" and ctx.catch_skip_logged != key:
            ctx.catch_skip_logged = key
            ctx.log(f"[catch: not catching {sp_name} L{e_lvl}: {hint.why}]", "res")
        if hint is not None and hint.kind == "throw":
            if run_line is None and not item_list_open(lines_now):
                return None
            ball_id = BALLS.get(hint.ball, POKE_BALL)           # unknown names fall back to the Poke Ball
            ball_name = BALL_NAME.get(hint.ball, "POKe BALL")
            ca = _attempt(ctx, species, e_lvl, ratio, dex_no, hint.ball)
            if release_slot is not None:
                ca["release_slot"] = release_slot   # the party-full policy's deposit slot rides on the record
            cur_c = next((ln for ln in lines_now if ">" in ln), "")
            dec = item_step(ctx, lines_now, cur_c, ball_id, ball_name,
                            f"CATCH {hint.ball or 'POKE'} at {ratio:.0%} HP (p={hint.p:.2f})")
            if dec is not None:
                if dec.rule == "item_use":  # the A that throws it
                    n = ctx.cave_catch_balls.get(species, 0) + 1
                    ctx.cave_catch_balls[species] = n
                    ctx.log(f"[catch: throwing {ball_name} {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map 0x{ctx.view.m:02X}]", "res")
                return _bag_press(ctx, ca, dec, key, sp_name)
            return None
        if hint is not None and hint.kind == "switch":
            btn = switch_press(frame_lines(ctx.view.tm), screen_lines(ctx.view.tm),
                               ctx.emu.read(MENU_ITEM), hint.slot)
            if btn is None:
                return None  # text scrolling / animation: the usual dialog handling runs
            n = (ctx.catch_switch[1] if ctx.catch_switch[0] == key else 0) + 1
            ctx.catch_switch = (key, n)
            if n > MAX_PRESSES:  # the menus are not what we think (the game refuses the switch): fight on
                ctx.catch_mode, ctx.catch_hint = False, None
                ctx.log(f"[catch: switch gave up after {MAX_PRESSES} presses on {sp_name}; fighting on]", "res")
                return Decision("B", "catch_switch_failed", "catch switch abandoned: backing out of the menu")
            return Decision(btn, "catch_switch", f"catch: {hint.why} (press {n})")
        if hint is None and ratio <= 0.35 and (run_line is not None or item_list_open(lines_now)):
            # No ROM data for the policy (catch_hint is None): the original rule - a POKE BALL at <=35% HP.
            # A ball throw never opens a party prompt.
            ca = _attempt(ctx, species, e_lvl, ratio, dex_no, None)
            cur_c = next((ln for ln in lines_now if ">" in ln), "")
            dec = item_step(ctx, lines_now, cur_c, POKE_BALL, "POKe BALL", f"CATCH at {ratio:.0%} HP")
            if dec is not None:
                if dec.rule == "item_use":  # the A that throws it
                    n = ctx.cave_catch_balls.get(species, 0) + 1
                    ctx.cave_catch_balls[species] = n
                    ctx.log(f"[catch: throwing ball {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map 0x{ctx.view.m:02X}]", "res")
                return _bag_press(ctx, ca, dec, key, sp_name)
        return None
