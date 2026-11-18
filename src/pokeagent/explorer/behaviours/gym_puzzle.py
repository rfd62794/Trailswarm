"""GymPuzzle: Lt. Surge's trash-can locks (map 0x5C) - walk to a can's stand tile, face it, press A
once, then judge the answer. Helpers and the why: explorer/gym_puzzle.py.

A press is judged from two sources (the controller's 2026-11-17 round-5 rules): the can's box text
collected in the press window (ctx.dialog pages plus a moved ctx.last_text - under --fast-text a box
can flash past every read and leave words in neither) is FINAL when it is a can's, and the REFEREE is
the fallback - the diff of the lock event byte (0xD773: bit1 = 1st lock, bit0 = 2nd) read around the
press. The D743/D744 pair is never judged: D744 is never cleared, so a stale index equal to the
pressed can is not a hit. In SEARCH the pair only ever logs; in ORACLE it steers the walk directly.

Caps modelled on field_cut: PRESS_CAP steps spent on one can, MAX_TRIES failed tries per can,
COOLDOWN steps after a give-up, plus the solver's own caps (MAX_PER_ATTEMPT / MAX_TOTAL - the
round-4 caps: attempts are bounded only by the run cap). The readiness hold (_hold_clear) is NOT
consulted: the puzzle may run only while the agent is already in the gym.

Any lock verdict (first / reset / second) also forgets learned walls touching the barrier cells:
a bump recorded while the gate was closed is stale the moment a lock moves (the controller's
round-3 live bounce: beat_surge oscillated under an OPEN gate on a learned '5,5,UP').
"""
from __future__ import annotations

from pokeagent.explorer import gym_puzzle as gp
from pokeagent.explorer import memory_purge
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import npc_positions

PRESS_CAP, MAX_TRIES, COOLDOWN, WAIT_BOX = 40, 3, 300, 6


class GymPuzzle(BehaviourBase):
    name = "gym_puzzle"

    def applies(self, ctx: ExplorerContext) -> bool:
        v = ctx.view
        if v.m != gp.GYM or v.battling or ctx.in_battle or v.box or ctx.proc is not None:
            return False
        if ctx.goals().get(gp.GOAL):  # the badge is already in hand: nothing left to open
            return False
        st = gp.state(ctx)
        if st["open"] or st["gave_up"] or ctx.step < st["cooldown_until"]:
            return False
        changed = gp.watch_barrier(st, v.tm, v.x, v.y)
        if changed:
            ctx.log(f"[gym_puzzle: {changed}]", "res")
        if gp.barrier_is_open(v.tm, v.x, v.y):    # all four stepping tiles 17 = the door is open
            st["open"] = True
            self._summary(ctx, st, "opened")
            return False
        return True

    def step(self, ctx: ExplorerContext) -> Decision | None:
        st = gp.state(ctx)
        locks = self._locks(ctx, st)
        if st["await"] is not None:
            return self._judge(ctx, st, locks)
        solver = self._solver(ctx, st)
        if solver is None:
            return None  # no can cells (planner not injected): leave the gym to exploration
        if solver.done:
            st["open"] = True
            return None
        if isinstance(solver, gp.Oracle):
            solver.set_locks(*locks)
            if locks != st["can_locks"]:  # the named can moved (the game re-randomizes D743): re-pick
                st["can"] = st["stand"] = None
        can = st["can"] or solver.next_can()
        st["can"], st["can_locks"] = can, locks
        if can is None:
            st["gave_up"] = True
            self._summary(ctx, st, "gave up")
            return None
        if st["presses"] >= PRESS_CAP:
            return self._fail_can(ctx, st, can, f"not pressed in {PRESS_CAP} steps")
        if st["stand"] is None:
            st["stand"] = self._stand(ctx, can)
        if st["stand"] is None:
            return self._fail_can(ctx, st, can, "no stand tile reachable")
        sx, sy, facing = st["stand"]
        v = ctx.view
        st["presses"] += 1
        if (v.x, v.y) != (sx, sy):
            path = self._path(ctx, (sx, sy))
            if not path:
                return self._fail_can(ctx, st, can, "no route to a stand tile")
            return Decision(path[0], "gym_puzzle_walk", f"gym puzzle: {len(path)} steps to can {gp.can_id(can)} {can}")
        if ctx.facing != facing:
            return Decision(facing, "gym_puzzle_face", f"gym puzzle: facing can {gp.can_id(can)} {can} ({facing})")
        st["await"] = {"can": can, "closed_at": ctx.talk_closed_frame, "waits": 0, "locks": locks,
                       "dlg": ctx.dialog, "dlen": len(ctx.dialog), "lt": ctx.last_text}
        return Decision("A", "gym_puzzle_press", f"gym puzzle: A at can {gp.can_id(can)} {can}")

    # --- one can's try: press -> box -> judge ---

    def _judge(self, ctx: ExplorerContext, st: dict, locks: tuple) -> Decision:
        aw = st["await"]
        can, solver = aw["can"], self._solver(ctx, st)
        text = self._press_text(ctx, aw)
        said = gp.classify(text) if gp.is_can_text(text) else None   # the can's own words, when seen
        ref = gp.referee_result(aw["locks"][2], locks[2]) if isinstance(solver, gp.Search) else None
        # the can's own words are final; the flag diff only judges a press whose box text was lost
        result = said if said is not None else ref
        if result is None:
            if ctx.talk_closed_frame > aw["closed_at"]:
                if text:  # a box did run, and it was not a can's: the press hit something else entirely
                    st["await"] = None
                    return self._fail_can(ctx, st, can, "the closed box was not a can's")
                result = "nothing"  # the answer box closed unseen and the RAM is unmoved: a real miss
            else:
                aw["waits"] += 1
                if aw["waits"] <= WAIT_BOX:
                    return no_press("gym_puzzle_wait", f"gym puzzle: waiting for can {gp.can_id(can)}'s answer")
                st["await"] = None
                return self._fail_can(ctx, st, can, "the press opened no box")
        st["await"] = None
        if solver is not None:
            solver.record(result)
            if result != "nothing":  # a lock moved: walls learned bumping the barrier are stale now
                gone = memory_purge.purge_walls_touching(ctx.mem.data, gp.GYM, gp.BARRIER)
                if gone:
                    ctx.log(f"[gym_puzzle: locks moved ({result}); forgot learned walls {gone}]", "res")
        self._log_press(ctx, can, result, "text" if said is not None else "referee")
        st["can"] = st["stand"] = None
        if solver is not None and solver.done:
            st["open"] = True
            self._summary(ctx, st, "opened")
        elif solver is not None and solver.gave_up:
            st["gave_up"] = True
            self._summary(ctx, st, "gave up")
        return no_press("gym_puzzle_judge", f"gym puzzle: can {gp.can_id(can)} said {result}")

    # --- pieces ---

    def _locks(self, ctx: ExplorerContext, st: dict) -> tuple:
        """(D743, D744, lock event byte @0xD773), read every step in both modes: ORACLE plans on it,
        SEARCH only logs and referees - and a move is logged either way (the game re-randomizes D743
        on every reset; D744 is never cleared - a stale index, not a live armed one)."""
        pair = (ctx.emu.read(gp.LOCK_ADDRS[0]), ctx.emu.read(gp.LOCK_ADDRS[1]), ctx.emu.read(gp.LOCK_FLAGS))
        prev = st.get("locks_seen")
        if prev is not None and pair != prev:
            ctx.log(f"[gym_puzzle: lock indices moved {prev} -> {pair}]", "res")
        st["locks_seen"] = pair
        return pair

    @staticmethod
    def _press_text(ctx: ExplorerContext, aw: dict) -> str:
        """The box text the press window produced: the pages appended to ctx.dialog since the A press (a
        new conversation gets a fresh list), plus ctx.last_text if it moved - a flashed box can leave
        words only there."""
        dlg = ctx.dialog
        pages = list(dlg if dlg is not aw["dlg"] else dlg[aw["dlen"]:])
        if ctx.last_text and ctx.last_text != aw["lt"] and ctx.last_text not in pages:
            pages.append(ctx.last_text)
        return " / ".join(pages)

    def _solver(self, ctx: ExplorerContext, st: dict):
        if st["solver"] is None:
            cans = gp.can_cells(ctx.route_plan, gp.GYM)
            if cans:
                mode = ctx.opts.gym_puzzle_mode
                ids = [ctx.emu.read(a) for a in (*gp.LOCK_ADDRS, gp.LOCK_FLAGS)] if mode == "oracle" else None
                st["solver"] = gp.make_solver(mode, cans, ids)
                ctx.log(f"[gym_puzzle: {len(cans)} cans on 0x{gp.GYM:02X}, mode {mode}"
                        + (f", lock indices {ids}" if ids else "") + "]", "res")
            else:
                st["solver"] = "dead"  # no ROM grid for the gym this run: stop asking every step
        return st["solver"] if isinstance(st["solver"], gp.Search) else None

    def _blocked(self, ctx: ExplorerContext) -> set:
        # temp_blocked is {(map, x, y): expiry frame} - expired entries stop blocking
        return {(x, y) for (m, x, y), exp in ctx.mem.temp_blocked.items() if m == gp.GYM and exp > ctx.frame} \
            | {(x, y) for x, y in npc_positions(ctx.emu)}

    def _path(self, ctx: ExplorerContext, goal: tuple) -> list | None:
        """The fan_club _ask pattern over the injected ctx.route_plan: learned walls + temp blocks."""
        plan = ctx.route_plan
        if plan is None:
            return None
        d = ctx.mem.data["maps"].get(str(gp.GYM), {})
        return plan((gp.GYM, ctx.view.x, ctx.view.y), {(gp.GYM, *goal)},
                    {gp.GYM: set(d.get("blocked", ()))}, {gp.GYM: self._blocked(ctx)})

    def _stand(self, ctx: ExplorerContext, can: tuple):
        blocked = self._blocked(ctx)
        above, below = (can[0], can[1] - 1), (can[0], can[1] + 1)
        reach = {c for c in (above, below) if self._path(ctx, c) is not None}  # a route exists (empty = there): standable
        return gp.stand_tile(can, reach, blocked)

    def _fail_can(self, ctx: ExplorerContext, st: dict, can: tuple, why: str) -> Decision:
        tries = st["tries"]
        tries[can] = tries.get(can, 0) + 1
        st["await"], st["stand"], st["presses"] = None, None, 0
        solver = self._solver(ctx, st)
        if tries[can] >= MAX_TRIES:
            st["can"] = None
            if solver is not None:
                solver.skip(can)
        st["cooldown_until"] = ctx.step + COOLDOWN
        self._log_press(ctx, can, f"miss ({why}; try {tries[can]}/{MAX_TRIES})")
        return no_press("gym_puzzle_fail", f"gym puzzle: can {gp.can_id(can)}: {why}")

    def _log_press(self, ctx: ExplorerContext, can: tuple, result: str, how: str = "referee") -> None:
        d1, d2, fl, cd = (ctx.emu.read(a) for a in (*gp.LOCK_ADDRS, gp.LOCK_FLAGS, gp.GYM_CAN_ADDR))
        ctx.log(f"[gym_puzzle: mode={ctx.opts.gym_puzzle_mode} can {gp.can_id(can)} at {can} -> {result} ({how}); "
                f"referee D743={d1} D744={d2} D773=0x{fl:02x} CD5B={cd} (read after the press)]", "res")

    def _summary(self, ctx: ExplorerContext, st: dict, outcome: str) -> None:
        if st["summarised"]:
            return
        st["summarised"] = True
        solver = st["solver"]
        score = solver.score() if isinstance(solver, gp.Search) else {}
        ctx.log(f"[gym_puzzle: {outcome}; score {score}]", "res")
