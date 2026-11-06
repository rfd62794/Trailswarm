"""menu: YES/NO answers, move-forgetting, goal-driven menu choices, and exploring the first untried option."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.dialog import goal_menu_choice, learn_decision, offered_starter, yesno_answer
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import frame_lines, is_menu, party_hp
from pokeagent.goals import check_goals


class Menu(BehaviourBase):
    name = "menu"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.box and is_menu(ctx.view.tm) and ctx.proc is None  # a running procedure drives its own menus

    def step(self, ctx: ExplorerContext) -> Decision | None:
        tm = ctx.view.tm
        # Explore menus: pick the first option we have not chosen at this interaction point yet.
        inter = ctx.inter; lines = frame_lines(tm)
        options = [ln.replace(">", "").strip() for ln in lines if ">" in ln or (ln.isupper() and len(ln.split()) <= 3)]
        cursor = next((ln.replace(">", "").strip() for ln in lines if ">" in ln), "")
        if {"YES", "NO"} <= {o.split()[-1] for o in options if o}:  # a YES/NO box
            question = " ".join(ln for ln in lines if "YES" not in ln and "NO" not in ln) or ctx.last_text
            context = " ".join(ctx.dialog[-4:]) + " " + question
            ql = question.lower()
            if "abandon" in ql:
                ans, why, forget = "YES", "abandon learning: only when we chose not to forget a move", None
                ctx.forget_move = None
            elif "learn" in context.lower() and ("make room" in ql or "delete" in ql):
                cur_moves = [ROM_KB["moves"].get(str(ctx.emu.read(0xD173 + i)), {}).get("name", "?") for i in range(4) if ctx.emu.read(0xD173 + i)] if ROM_KB else []
                ans, why, forget = learn_decision(context, cur_moves)
                ctx.forget_move = forget
            else:
                ans, why = yesno_answer(context, ctx.opts.starter, buy_magikarp=not check_goals(ctx.emu, ctx)["buy_magikarp"],
                                      offer_text=" ".join(ctx.dialog[-12:]) + " " + question)  # the price line scrolls past the name
            ctx.yesno = {"question": question[:80], "answer": ans}
            offered = offered_starter(context)
            if ans == "NO" and offered:  # remember THIS ball so we try another one
                ctx.declined_balls[(ctx.view.m, ctx.view.x, ctx.view.y, ctx.facing)] = offered
            if cursor.endswith(ans):
                return Decision("A", "yesno_answer", f"YES/NO box: answering {ans} ({why}) to \"{question[:50]}\"")
            return Decision("DOWN" if ans == "NO" else "UP", "yesno_cursor", f"YES/NO box: moving the cursor to {ans} ({why})")
        if ctx.forget_move:  # the 'which move to forget' list: pick the weakest by cartridge value
            normf = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
            if normf(cursor) == normf(ctx.forget_move):
                fm = ctx.pop("forget_move"); return Decision("A", "forget_press", f"forgetting {fm} for the new move")
            if any(normf(o) == normf(ctx.forget_move) for o in options):
                return Decision("DOWN", "forget_cursor", f"move list: cursor to {ctx.forget_move}")
        goals_now = check_goals(ctx.emu, ctx)
        want = goal_menu_choice(goals_now, options)
        heal_opt = next((o for o in options if o.strip().endswith("HEAL") and "POK" not in o), None)
        if heal_opt and not want:  # Pokecenter counter 'HEAL / CANCEL': heal whenever any party member is hurt
            hp_c, mx_c = party_hp(ctx.emu)
            if mx_c and hp_c < mx_c:
                want = heal_opt
        if not want and goals_now.get("potion") and any("WITHDRAW" in o or "DEPOSIT" in o for o in options):
            return Decision("B", "pc_potion_done", "potion already in the bag: nothing else to do at the PC, backing out")
        if want:  # a goal tells us which option to take here
            if cursor == want:
                return Decision("A", "goal_menu_press", f"goal menu choice: '{want}'")
            return Decision("DOWN", "goal_menu_cursor", f"goal menu choice: moving the cursor toward '{want}'")
        tried = (inter or {}).get("entry", {}).get("choices", []) + (inter or {}).get("choices", [])
        if any(cursor.endswith(w) for w in ("CANCEL", "LOG OFF", "EXIT", "QUIT")):
            # Exits are always a fine choice once nothing here is wanted (seen 2026-11-03: the agent sat on
            # 'CANCEL' pressing DOWN because CANCEL counted as 'already tried').
            return Decision("A", "leave_menu", f"menu: cursor on '{cursor}' - leaving this menu")
        if cursor and cursor not in tried:
            return Decision("A", "menu_new_option", f"menu open, cursor on '{cursor}' (new) - choosing it")
        if any(o not in tried for o in options):
            return Decision("DOWN", "menu_next_option", f"menu open, '{cursor}' already tried - moving the cursor down")
        return Decision("B", "menu_back", "menu open, every option tried here - backing out")
        return None

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.box_streak >= 12  # a menu that stayed open this long is backed out of
