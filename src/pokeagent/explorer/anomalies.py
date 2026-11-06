"""AnomalyMonitor: watches every press for stuck NPCs, teleports, impossible RAM, frozen screens, endless text/battles.

Built per run (``AnomalyMonitor.for_ctx``), fed by ``Presser.press`` (``observe``) and ``Engine.step``
(``note_decision``). Findings go to runs/anomalies.jsonl via ``anomaly_record``; a wanderer NPC that blocks the
agent's next tile also sets ``block`` so the AnomalyWait behaviour can wait, then route around it for a while.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pokeagent.explorer.anomaly_detectors import Detectors, Obs
from pokeagent.explorer.anomaly_ram import impossible_state
from pokeagent.explorer.anomaly_record import RECENT_DECISIONS, AnomalyLog
from pokeagent.explorer.anomaly_sprites import doorway_tiles, read_sprites, walkable_tiles, wanderer_slots
from pokeagent.explorer.perceive import DIRS, TILEMAP, TILEMAP_LEN

WAIT_PRESSES = 6          # presses spent waiting for a blocking wanderer to move before routing around it
TEMP_BLOCK_PRESSES = 40   # steps the blocker's tile stays temporarily blocked for routing (never learned as a wall)
JOY_IGNORE, SPRITE_TABLE = 0xCD6B, (0xC100, 0x200)  # wJoyIgnore (pokered.sym); the 15 sprite state slots


@dataclass
class Block:
    """A wanderer NPC standing on the tile the agent is pressing into."""
    map: int
    tile: tuple
    slot: int
    player: tuple
    waited: int = 0


class AnomalyMonitor:
    def __init__(self, runs_dir: Path | str, run: str, valid_maps=None, log: AnomalyLog | None = None) -> None:
        self.log = log or AnomalyLog(runs_dir, run)
        self.valid_maps = valid_maps
        self.det = Detectors()
        self.recent: list[dict] = []
        self.block: Block | None = None
        self.findings: list[dict] = []   # records written this run (tests, summaries)

    @classmethod
    def for_ctx(cls, ctx, valid_maps: frozenset[int] | None = None) -> "AnomalyMonitor":
        """valid_maps: map ids with a sane ROM header (atlas.rom_maps.valid_map_ids); None skips that one check."""
        return cls(ctx.run_dir.parent, ctx.run_dir.name, valid_maps)

    def note_decision(self, rec: dict) -> None:
        self.recent.append(rec)
        del self.recent[:-RECENT_DECISIONS]

    def reset(self) -> None:
        """After a load_state/teleport by the operator: forget the history so the jump is not an anomaly."""
        self.det.reset()
        self.block = None

    def build_obs(self, ctx, fr) -> Obs:
        emu, (m, x, y) = ctx.emu, fr.after
        md = ctx.mem.m(m)
        sig = hash(emu.read_range(TILEMAP, TILEMAP_LEN) + emu.read_range(*SPRITE_TABLE))
        return Obs(step=ctx.step, frame=ctx.frame, map=m, x=x, y=y, button=fr.name, prev=tuple(fr.before),
                   sprites=read_sprites(emu), wanderers=wanderer_slots(md.get("npcs", {})),
                   doors=doorway_tiles(md.get("warps", {})), walkable=walkable_tiles(md), warps=md.get("warps", {}),
                   jumps=md.get("jumps", {}), box=fr.box_after, battle=emu.read(0xD057) != 0,
                   joy_ignore=emu.read(JOY_IGNORE), screen_sig=sig, broken=impossible_state(emu, self.valid_maps))

    def observe(self, ctx, fr) -> list[dict]:
        """Run every detector on the press just made; returns the records written."""
        obs = self.build_obs(ctx, fr)
        self._track_block(obs)
        self._expire_temp_blocks(ctx)
        written = []
        for f in self.det.update(obs):
            if self.log.allow(f.type, f.map, f.tile, obs.step):
                rec = self.log.write(f, step=obs.step, frame=obs.frame, emu=ctx.emu, decisions=self.recent, player=(obs.x, obs.y))
                ctx.log(f"*** ANOMALY {f.type} at map 0x{f.map:02X} ({f.x},{f.y}) cause={rec['cause_hint']} ***", "res")
                written.append(rec)
        self.findings += written
        return written

    # --- mitigation: a wanderer on the agent's next tile ---
    def _track_block(self, o: Obs) -> None:
        b = self.block
        if b is not None and (b.map != o.map or b.player != (o.x, o.y) or o.sprites.get(b.slot, (0, None, None))[1:] != b.tile):
            self.block = b = None  # the NPC left, or we moved: nothing blocks any more
        if b is None and o.button in DIRS and o.prev == (o.map, o.x, o.y) and not o.box and not o.battle:
            dx, dy = DIRS[o.button]
            for slot, (pic, sx, sy) in o.sprites.items():
                if slot in o.wanderers and (sx, sy) == (o.x + dx, o.y + dy):
                    self.block = Block(o.map, (sx, sy), slot, (o.x, o.y))

    def reroute(self, ctx) -> None:
        """The wait is over: treat the blocker's tile as blocked for TEMP_BLOCK_PRESSES steps and replan."""
        b, self.block = self.block, None
        if b is None:
            return
        ctx.mem.temp_blocked[(b.map, *b.tile)] = ctx.step + TEMP_BLOCK_PRESSES
        ctx.frontier_route, ctx.frontier_target, ctx.frontier_at = [], None, None

    @staticmethod
    def _expire_temp_blocks(ctx) -> None:
        tb = getattr(ctx.mem, "temp_blocked", {})
        for k in [k for k, until in tb.items() if until <= ctx.step]:
            del tb[k]
