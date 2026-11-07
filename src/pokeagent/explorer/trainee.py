"""Record the Magikarp switch-training numbers into the run's meta.json (tools/status.py prints them)."""
from __future__ import annotations

import json

from pokeagent.explorer import party_log
from pokeagent.explorer.economy import ledger
from pokeagent.explorer.context import ExplorerContext
from pokeagent.goals import SIDE_GOALS, check_goals
from pokeagent.magikarp import magikarp_stats


def record_trainee(ctx: ExplorerContext) -> None:
    """Best effort: a failure here must never end a run."""
    try:
        mp = ctx.run_dir / "meta.json"
        meta = json.loads(mp.read_text())
        goals = check_goals(ctx.emu, ctx)
        meta["magikarp"] = {**(magikarp_stats(ctx.emu) or {}), "battles_shared": ctx.magikarp_shared, "battles": ctx.battles}
        meta["side_goals"] = {g: bool(goals.get(g)) for g in SIDE_GOALS}
        meta["xp_summary"] = party_log.of(ctx).summary(ctx)
        meta["econ_summary"] = ledger.of(ctx).summary()
        mp.write_text(json.dumps(meta))
    except Exception:
        pass
