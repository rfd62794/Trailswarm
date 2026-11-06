"""battle_moves: choose the move (learned damage + cartridge knowledge, PP guard) or fall back to FIGHT."""
from __future__ import annotations

import re

from pokeagent.explorer.battle import (
    enemy_max_hp, enemy_types, move_by_name, move_rule, move_scores, norm_name, observed_damage,
    is_typed_attack,
)
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.battle import _finalize_pending_effect
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB


MENU_CURSORS = ("", "FIGHT", "PKMN", "ITEM", "RUN", "CANCEL")  # a cursor on the battle menu is not a move


NON_HIT_NOTES = ("stat-down", "heal", "foe already", "fight ends")


def pick_catch_move(pool: list[str], tags: dict[str, str], kscore, norm) -> tuple[str, str]:
    """Catch mode: a sleep / paralyse move first (it raises the catch rate), else the weakest damaging hit,
    else the first usable move (only a heal or stat move left - never an empty min())."""
    status = [mv for mv in pool if "catch-status" in tags.get(norm(mv), "")]
    if status:
        return max(status, key=kscore), "status before the catch"
    hits = [mv for mv in pool if kscore(mv) > 0 and not ("[" in tags.get(norm(mv), "") and any(x in tags.get(norm(mv), "") for x in NON_HIT_NOTES))]
    if hits:
        return min(hits, key=kscore), "weakest hit, catching"
    return pool[0], "no damaging move usable: first move"


class BattleMoves(BehaviourBase):
    name = "battle_moves"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling and ctx.bv is not None

    def step(self, ctx: ExplorerContext) -> Decision | None:
        lines_now = ctx.view.lines
        bv = ctx.bv
        kind, hp, mx, species = bv.kind, bv.hp, bv.mx, bv.species
        my_sp, my_lvl, e_lvl = bv.my_sp, bv.my_lvl, bv.e_lvl
        cur, want_potion = bv.cur, bv.want_potion
        # --- move choice with memory: damage dealt per (enemy species, move) is learned from the enemy HP drop
        #     after our move; untried moves are tried first (variety), then the best average; 0-PP moves skipped ---
        enemy_hp = (ctx.emu.read(0xCFE6) << 8) | ctx.emu.read(0xCFE7)
        pm = ctx.pending_move
        if pm and pm["species"] == species and enemy_hp < pm["enemy_hp"]:
            dealt = pm["enemy_hp"] - enemy_hp
            stats = ctx.mem.data.setdefault("move_damage", {}).setdefault(f"{species}:{pm['move']}", [])
            stats.append(dealt); del stats[:-20]; ctx.pending_move = None
            key = f"{my_sp}L{my_lvl}:{pm['move']}->{species}L{e_lvl}"  # our move, our level, their species and level
            rec = ctx.mem.data.setdefault("damage_dealt", {}).setdefault(key, [])
            rec.append(dealt); del rec[:-20]
            # Generalised lesson: fraction of the enemy's max HP per hit, keyed move + defender types.
            if pm.get("typed") and pm.get("enemy_max"):
                dk = ctx.mem.data.setdefault("damage_by_type", {}).setdefault(f"{pm['move']}|{pm.get('def_key', '?')}", [])
                dk.append(round(dealt / pm["enemy_max"], 4)); del dk[:-20]
            # The result message may still be scrolling: the battle-text scan counts super/weak/none;
            # a damaging hit with no message finalises as neutral. Skip if the scan already saw it.
            fx = ctx.fx_last_fx
            seen = bool(fx and fx.get("step", -1) >= pm.get("step", 0)
                        and norm_name(fx.get("move", "")) == norm_name(pm["move"]))
            if pm.get("typed") and pm.get("move_type") and pm.get("def_types") and not seen:
                _finalize_pending_effect(ctx)  # never overwrite a result still awaiting its message
                ctx.pending_effect = {"move": pm["move"], "move_type": pm["move_type"],
                                      "def_types": pm["def_types"], "step": ctx.step}
        # The move menu reads: TYPE/ | NORMAL | 29/30 | TACKLE | >TAIL WHIP  -> moves are the lines AFTER the PP line
        pp_idx = next((i for i, ln in enumerate(lines_now) if re.fullmatch(r"\d+/\d+", ln.replace(">", "").strip())), None)
        move_lines = [ln for ln in lines_now[pp_idx + 1:] if ln.replace(">", "").strip() not in ("", "-")] if pp_idx is not None else []
        cursor_mv = next((ln.replace(">", "").strip() for ln in move_lines if ">" in ln), None)
        if cursor_mv and 1 <= len(move_lines) <= 4:  # the move menu
            moves = [ln.replace(">", "").strip() for ln in move_lines]
            # --- no-PP guard, two layers (Robert, 2026-11-04: reselecting an empty move stalls the run) ---
            # 1) the game's refusal: an A-press that drew the 'no PP left' text marks the move unusable this battle
            # (a DISABLED move - "The move is disabled!" - is refused the same way: 1,195 presses were lost on it, 2026-11-05)
            if any("PP" in ln.upper() or "DISABLED" in ln.upper() for ln in lines_now):
                rejected = ctx.pop("last_move_choice")
                if rejected:
                    ctx.no_pp.add(rejected)
                    ctx.log(f"[{rejected} was refused (no PP / disabled) - not reselecting it this battle]", "res")
            # 2) the PP bytes already trusted by move_scores (wBattleMonPP 0xD02D-0xD030, slots = list order)
            pp_of = [ctx.emu.read(0xD02D + i) & 0x3F for i in range(4)]
            avail = [mv for i, mv in enumerate(moves)
                     if (i >= len(pp_of) or pp_of[i] > 0) and mv not in ctx.no_pp]
            if not avail:  # every move refused or reads 0 PP: B out so the game can fall to STRUGGLE
                ctx.all_pp_out = ctx.all_pp_out + 1
                if ctx.all_pp_out > 1:
                    return Decision("B", "pp_out_struggle", "all moves out of PP: leaving the move list for STRUGGLE")
            else:
                ctx.all_pp_out = 0
            pool = avail or moves  # a stale all-zero PP read must not freeze the chooser: fall back
            enemy_max = enemy_max_hp(ctx.emu)
            defs = enemy_types(ctx.emu)
            def_key = "/".join(defs)
            def score(mv):
                return observed_damage(ctx.mem.data, species, mv, def_key, enemy_max)
            tried = [mv for mv in pool if score(mv)[0]]
            ks = move_scores(ctx.emu, catching=ctx.catch_mode)  # cartridge knowledge: power x type chart x STAB x accuracy, 0 when out of PP
            norm0 = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
            known = {norm0(k): v for k, v in ks.items()}
            tags = {norm0(k): v[1] for k, v in ks.items()}
            if known and any(known.get(norm0(mv), (0, ""))[0] > 0 for mv in pool):
                # Willing to try: a damaging move never used against this species gets one trial (x1.3 bonus)
                def kscore(mv):
                    base = known.get(norm0(mv), (0, ""))[0]
                    return base * (1.3 if base > 0 and mv not in tried else 1.0)
                if ctx.catch_mode:  # a sleep / paralyse move first (it raises the catch rate), else the weakest damaging hit
                    target, ctx.move_reason = pick_catch_move(pool, tags, kscore, norm0)
                else:
                    target = max(pool, key=lambda mv: (kscore(mv), score(mv)[1]))
                    ctx.move_reason = "" if target in tried else "first try"
            else:  # no knowledge (or all out of PP): variety first, then the best observed damage
                target = next((mv for mv in pool if mv not in tried), None) or max(pool, key=lambda mv: score(mv)[1])
                ctx.move_reason = "untried" if target not in tried else f"best avg {score(target)[1]:.1f} dmg"
            ctx.move_tag = move_rule(ctx.emu, target)  # the matchup it is aiming at, even while the cursor walks
            norm = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
            ctx.move_nav = ctx.move_nav + 1
            if norm(cursor_mv) == norm(target) or ctx.move_nav > 5:  # never bounce: after 5 moves take what is under the cursor
                chosen = cursor_mv if ctx.move_nav > 5 else target
                ctx.move_nav = 0
                tag = move_rule(ctx.emu, chosen)
                ctx.move_tag = tag
                ctx.pending_move = {"species": species, "move": chosen, "enemy_hp": enemy_hp,
                                    "enemy_max": enemy_max, "def_key": def_key, "def_types": defs,
                                    "move_type": (move_by_name(chosen) or {}).get("type"), "step": ctx.step, "typed": is_typed_attack(chosen)}
                ctx.last_move_choice = chosen  # a 'no PP left' text next loop marks this move unusable
                ename = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), f"#{species}")
                why = f"BATTLE vs {ename} L{ctx.emu.read(0xCFF3)}: {tag}"
                if ctx.move_reason:
                    why += f" ({ctx.move_reason})"
                return Decision("A", tag, why)
            return Decision("DOWN", "move_cursor", f"move menu: cursor to {target} (now on {cursor_mv})")
        if ">ITEM" in cur and not want_potion:  # never open ITEM without a reason (a bare CANCEL list stalls)
            return Decision("UP", "back_to_fight", "battle menu: back up to FIGHT")
        if any("CANCEL" in ln and ">" in ln for ln in lines_now):
            return Decision("A", "close_empty_list", "battle: closing an empty list")
        if any("DISABLED" in ln.upper() for ln in lines_now):
            # "The move is disabled!" leaves the move list on screen WITHOUT its PP line, with the cursor on the refused move:
            # remember it and step the cursor off it (the PP-line branch above never saw this screen; 1,195 presses lost, 2026-11-05)
            names = [ln.replace(">", "").strip() for ln in lines_now
                     if "DISABLED" not in ln.upper() and ln.replace(">", "").strip().upper() not in MENU_CURSORS]
            stuck = next((ln.replace(">", "").strip() for ln in lines_now
                          if ln.strip().startswith(">") and ln.replace(">", "").strip().upper() not in MENU_CURSORS), None)
            if stuck and stuck in ctx.no_pp:
                # Already excluded: walk straight to the first usable move (never UP then back DOWN onto it - Route 3 loop)
                usable = [n for n in names if n not in ctx.no_pp]
                if usable:
                    return Decision("DOWN" if names.index(usable[0]) > names.index(stuck) else "UP", "disabled_move",
                                    f"move {stuck} is disabled: heading straight to {usable[0]}")
            elif stuck and not any(n in ctx.no_pp for n in names):
                ctx.no_pp.add(stuck)
                return Decision("UP", "disabled_move", f"move {stuck} is disabled: moving the cursor off it")
            # cursor already on a usable move (the notice is still drawn): fall through and take it
        return Decision("A", "fight", f"BATTLE kind=0x{kind:02X} HP {hp}/{mx}: FIGHT")
