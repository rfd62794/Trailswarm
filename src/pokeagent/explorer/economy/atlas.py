"""Cross-run economy ledger: runs/economy.json keeps sufficient statistics plus a byte cursor into runs/battles.jsonl, so
``refresh(runs_dir)`` folds only what is new (the grind atlas pattern, grind/refresh.py). Reads runs/ only; writes runs/economy.json only.

  hp        HP the party lost per fight, overall and per map ([fights, HP lost]); the potion sizing reads it
  income    prize money by source (trainer fights, other fights, item sales) and per map
  blackouts count and yen lost, and how many happened with no Potion in the bag (``potions_before`` in the battle record)
  spend     per item: quantity and yen (from each finished run's meta.json econ_summary)
  uses      per item: uses, HP restored, split by why/behaviour; ``heal_trips_avoided`` = field potions drunk instead of walking
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.explorer.economy.hp_stats import hp_lost

FILE = "economy.json"
TRAINER = 2  # battle record "kind": 1 wild, 2 trainer


def load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("version") == 1:
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "cursor": {"offset": 0}, "runs_done": [], "hp": {"overall": [0, 0], "by_map": {}},
            "income": {"trainer": 0, "other": 0, "sales": 0, "by_map": {}}, "blackouts": {"n": 0, "yen": 0, "no_potion": 0, "by_map": {}},
            "spend": {}, "uses": {}, "heal_trips_avoided": 0, "stock_by_map": {}}


def _bump(row: list, *vals: int) -> None:
    for i, v in enumerate(vals):
        row[i] += v


def fold_battle(doc: dict, rec: dict) -> None:
    m = str(rec.get("map"))
    lost = hp_lost(rec)
    if lost is not None:
        _bump(doc["hp"]["overall"], 1, lost)
        _bump(doc["hp"]["by_map"].setdefault(m, [0, 0]), 1, lost)
    before, after = rec.get("money_before"), rec.get("money_after")
    if before is None or after is None:
        return
    delta, inc, bo = after - before, doc["income"], doc["blackouts"]
    if delta > 0:
        inc["trainer" if rec.get("kind") == TRAINER else "other"] += delta
        inc["by_map"][m] = inc["by_map"].get(m, 0) + delta
    elif delta < 0 and rec.get("won") is False and not rec.get("fled"):
        bo["n"] += 1
        bo["yen"] += -delta
        bo["no_potion"] += int(rec.get("potions_before") == 0)
        bo["by_map"][m] = bo["by_map"].get(m, 0) + 1


def fold_new_battles(doc: dict, runs_dir: Path) -> int:
    path, cur = runs_dir / "battles.jsonl", doc["cursor"]
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size < cur.get("offset", 0):  # a shrunken log starts the battle statistics over
        cur["offset"] = 0
        fresh = load(Path("/nonexistent"))
        doc["hp"], doc["blackouts"] = fresh["hp"], fresh["blackouts"]
        doc["income"].update(trainer=0, other=0, by_map={})
    with path.open("rb") as fh:
        fh.seek(cur["offset"])
        data = fh.read()
    end, n = data.rfind(b"\n") + 1, 0  # whole lines only
    for line in data[:end].splitlines():
        try:
            fold_battle(doc, json.loads(line))
            n += 1
        except (ValueError, TypeError, IndexError):
            continue
    cur["offset"] += end
    return n


def fold_run(doc: dict, econ: dict) -> None:
    """One finished run's econ_summary: purchases, sales, item uses, live-read Mart stock."""
    for p in econ.get("purchases", []):
        row = doc["spend"].setdefault(str(p["item"]), {"qty": 0, "yen": 0})
        row["qty"] += p["qty"]
        row["yen"] += p["cost"]
    doc["income"]["sales"] += sum(s["gained"] for s in econ.get("sales", []))
    for u in econ.get("uses", []):
        row = doc["uses"].setdefault(str(u["item"]), {"n": 0, "hp_restored": 0, "battle": 0, "by_why": {}})
        gained = max(0, u["hp_after"] - u["hp_before"])
        row["n"] += 1
        row["hp_restored"] += gained
        row["battle"] += int(bool(u["battle"]))
        why = row["by_why"].setdefault(u["why"], [0, 0])
        _bump(why, 1, gained)
        doc["heal_trips_avoided"] += int(str(u["why"]).startswith("field potion"))
    for m, stock in (econ.get("stock_seen") or {}).items():
        if stock:
            doc["stock_by_map"][str(m)] = stock


def fold_new_runs(doc: dict, runs_dir: Path) -> int:
    done, n = set(doc["runs_done"]), 0
    for meta in sorted(runs_dir.glob("*/meta.json")):
        if meta.parent.name in done:
            continue
        try:
            econ = json.loads(meta.read_text(encoding="utf-8")).get("econ_summary")
        except (OSError, ValueError):
            continue
        if econ is None:
            continue  # unfinished run: its summary is written at the end
        fold_run(doc, econ)
        doc["runs_done"].append(meta.parent.name)
        n += 1
    return n


def save(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def refresh(runs_dir: str | Path = "runs") -> dict:
    """Entry point for the swarm supervisor: fold new battles and finished runs, save runs/economy.json.
    Returns {"battles", "runs", "offset"}. Never raises on missing data."""
    runs = Path(runs_dir)
    if not runs.is_dir():
        return {"battles": 0, "runs": 0, "offset": 0}
    doc = load(runs / FILE)
    nb, nr = fold_new_battles(doc, runs), fold_new_runs(doc, runs)
    save(runs / FILE, doc)
    return {"battles": nb, "runs": nr, "offset": doc["cursor"]["offset"]}
