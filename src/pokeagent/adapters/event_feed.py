"""Derives the agent's event stream from the live game, on the emulator thread (appends only, no I/O).

``EventFeed.observe(...)`` runs where the snapshot is built (every few ticks). It diffs position, battle RAM, goals, the
learned map model and the human hold against what it saw last time and emits typed events into an ``EventBus``.
Layer rule: adapters/ never import viewer/.
"""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB
from pokeagent.party_view import read_battle_view
from pokeagent.ram_symbols import ENEMY_MON, IS_IN_BATTLE
from pokeagent.world import events as ev

BATTLE_FLAG = IS_IN_BATTLE
ENEMY_SPECIES = ENEMY_MON   # wEnemyMonSpecies (internal id); 0xCFD7 is wPlayerMoveMaxPP, not a species
STALL_STEPS = 200      # game steps without moving before a stall event
_DELTA = {(0, -1): "UP", (0, 1): "DOWN", (-1, 0): "LEFT", (1, 0): "RIGHT"}
_LEARN = (("blocked", "wall"), ("warps", "warp"), ("jumps", "jump"), ("encounters", "encounter"))


def _u16(emu, a: int) -> int:
    return (emu.read(a) << 8) | emu.read(a + 1)


class EventFeed:
    def __init__(self, bus: ev.EventBus | None = None) -> None:
        self.bus = bus or ev.EventBus()
        self._pos: tuple[int, int, int] | None = None
        self._facing = "DOWN"
        self._battle = False
        self._turn = 0
        self._last_hp: tuple = ()
        self._goals: dict[str, bool] = {}
        self._hold = False
        self._dec_key: tuple = ()
        self._counts: dict[tuple[str, str], int] = {}
        self._move_step = 0
        self._stalled = False

    def observe(self, emu, ctx, mem=None, dec=None, outcome: str = "", hold: bool = False, goals: dict | None = None) -> None:
        self._position(emu, ctx)
        self._battle_events(emu, dec)
        self._decision(dec, outcome)
        for name, done in sorted((goals or {}).items()):
            if self._goals.get(name) != done:
                self._goals[name] = done
                self.bus.emit(ev.Goal(name=name, status="done" if done else "current"))
        if hold != self._hold:
            self._hold = hold
            self.bus.emit(ev.HumanHold(on=hold))
        if mem is not None:
            self._learned(mem)

    def _position(self, emu, ctx) -> None:
        pos = (emu.read(0xD35E), emu.read(0xD362), emu.read(0xD361))
        step = int(getattr(ctx, "step", 0))
        if pos == self._pos:
            if step - self._move_step >= STALL_STEPS and not self._stalled:
                self._stalled = True
                self.bus.emit(ev.Stall(reason="no movement", steps=step - self._move_step))   # game steps, not observations
            return
        prev, self._pos, self._move_step, self._stalled = self._pos, pos, step, False
        if prev is not None and prev[0] != pos[0]:
            self.bus.emit(ev.MapChange(map=pos[0], x=pos[1], y=pos[2], prev_map=prev[0]))
        elif prev is not None:
            self._facing = _DELTA.get((pos[1] - prev[1], pos[2] - prev[2]), self._facing)
        self.bus.emit(ev.Move(map=pos[0], x=pos[1], y=pos[2], facing=self._facing, step=step))

    def _mon(self, internal: int) -> str:
        return (ROM_KB or {}).get("name_of_internal", {}).get(str(internal), f"#{internal}")

    def _battle_events(self, emu, dec) -> None:
        on = emu.read(BATTLE_FLAG) != 0
        # None while wBattleMon is stale (species 0 at battle start): no own mon and an empty hp tuple then,
        # exactly as when not in battle - a stale block must never feed the event stream.
        bm = read_battle_view(emu).battle_mon if on else None
        hp = (bm.hp, bm.max_hp, _u16(emu, 0xCFE6), _u16(emu, 0xCFF4)) if bm is not None else ()
        if bm is not None and not self._battle:
            self._turn, self._last_hp = 0, hp
            self.bus.emit(ev.BattleStart(species=self._mon(emu.read(ENEMY_SPECIES)), enemy_level=emu.read(0xCFF3),
                                         own_species=self._mon(bm.species), own_level=bm.level,
                                         hp=hp[0], max_hp=hp[1], enemy_hp=hp[2], enemy_max_hp=hp[3]))
        elif bm is not None and hp != self._last_hp:
            self._turn += 1
            self._last_hp = hp
            self.bus.emit(ev.BattleTurn(turn=self._turn, hp=hp[0], max_hp=hp[1], enemy_hp=hp[2], enemy_max_hp=hp[3],
                                        move=str(getattr(dec, "button", "") or ""), plan=str(getattr(dec, "why", "") or "")))
        elif self._battle and not on:
            last = self._last_hp
            res = "lost" if last and last[0] == 0 else "won" if last and last[2] == 0 else "ended"
            self.bus.emit(ev.BattleEnd(result=res, turns=self._turn))
        if bm is not None or not on:
            self._battle = on

    def _decision(self, dec, outcome: str) -> None:
        if dec is None:
            return
        key = (getattr(dec, "behaviour", ""), getattr(dec, "rule", ""), getattr(dec, "button", ""), outcome)
        if key != self._dec_key:
            self._dec_key = key
            self.bus.emit(ev.Decision(behaviour=key[0], rule=key[1], button=key[2], outcome=outcome, driver="explorer"))

    def _learned(self, mem) -> None:
        for mid, d in (mem.data.get("maps") or {}).items():
            for field, kind in _LEARN:
                cur = d.get(field) or {}
                seen = self._counts.get((mid, field), 0)
                if len(cur) == seen:
                    continue
                for k in list(cur)[seen:]:
                    self._emit_learn(kind, int(mid), k, cur[k] if isinstance(cur, dict) else None)
                self._counts[(mid, field)] = len(cur)

    def _emit_learn(self, kind: str, mid: int, key: str, val) -> None:
        a = key.split(",")
        try:
            x, y = int(a[0]), int(a[1])
        except (ValueError, IndexError):
            return
        dest = [int(v) for v in val] if kind in ("warp", "jump") and isinstance(val, list) else None
        self.bus.emit(ev.Learn(kind=kind, map=mid, x=x, y=y, dir=a[2] if len(a) > 2 else "", dest=dest))
