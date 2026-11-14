"""Party rules: the registry of rules a save state's team must satisfy. ``fp["team"]`` records what the party IS;
these rules name what it must not be - ``wild-never-catch`` refuses the wild Harden-only KAKUNA that cannot be
trained (Robert, 2026-11-14). A gate stamp records ``fp["rule_violations"]`` so no consumer needs a kb;
``verdict`` is ``unknown`` when team or kb tables are missing."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pokeagent import statefp, team_fp
from pokeagent.explorer import catch_list
from pokeagent.game.stores import store_path
from pokeagent.knowledge.kb import table

ROOT = Path(__file__).resolve().parents[2]
_KB: dict | None | bool = False   # False = not tried yet; None = tried and absent


def rom_kb() -> dict | None:
    """kb/rom_tables.json (the table statescmd._kb_json reads), cached; None when absent or unreadable."""
    global _KB
    if _KB is False:
        try:
            _KB = json.loads(store_path("kb/rom_tables.json", root=ROOT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _KB = None
    return _KB


@dataclass(frozen=True)
class Rule:
    name: str
    check: Callable[[dict, dict | None], list[str]]    # (fp, kb) -> violation texts, [] when the state complies


def _wild_never_catch(fp: dict, kb: dict | None) -> list[str]:
    names = table(kb, "name_of_internal")
    out = []
    for i, m in enumerate(fp.get("team") or (), 1):
        if not isinstance(m, dict):
            continue
        name = names.get(str(m.get("species")))
        if catch_list.wild_never_catch(name, team_fp.moves_of(m, kb)):
            out.append(f"wild {name} L{m.get('level')} (Harden only) in slot {i}")
    return out


RULES: tuple[Rule, ...] = (Rule("wild-never-catch", _wild_never_catch),)


def broken(fp: dict | None, kb: dict | None) -> list[tuple[str, str]]:
    """(rule name, violation text) per broken rule; recorded stamp-time violations count as rule 'recorded'."""
    fp = fp or {}
    seen = [t for t in fp.get("rule_violations") or () if isinstance(t, str)]
    return [("recorded", t) for t in seen] + \
        [(r.name, t) for r in RULES for t in r.check(fp, kb) if t not in set(seen)]


def violations(fp: dict | None, kb: dict | None) -> list[str]:
    """Every violation text on record for ``fp`` (recorded first, then live rules)."""
    return [t for _, t in broken(fp, kb)]


def verdict(fp: dict | None, kb: dict | None) -> str:
    """``clean`` | ``violation`` | ``unknown`` (no team, or the kb cannot name species/moves)."""
    fp = fp or {}
    if fp.get("rule_violations"):
        return "violation"
    if fp.get("team") is None or not (table(kb, "name_of_internal") and table(kb, "moves")):
        return "unknown"
    return "violation" if violations(fp, kb) else "clean"


def gate_stamp(fp, state, kb, log=None) -> list[tuple[str, str]]:
    """The stamp-time hook: write ``fp["rule_violations"]`` into the sidecar and log
    ``[state gate: <name> breaks <rule>: <text>]``. Never raises into the caller's run."""
    try:
        found = broken(fp, kb)
        if found and isinstance(fp, dict):
            fp["rule_violations"] = list(dict.fromkeys(t for _, t in found))
            statefp.write(state, fp)
            for rule, text in (found if log else ()):
                log(f"[state gate: {Path(state).name} breaks {rule}: {text}]")
        return found
    except Exception:  # noqa: BLE001  a gate failure must never end a run
        return []


def quarantine_dest(fp_new, dest, kb) -> Path:
    """``dest`` normally; ``<stem>.quarantine.state`` when ``fp_new`` violates and the ``dest`` on disk is a clean
    checkpoint - a violating state never overwrites a clean one."""
    dest = Path(dest)
    try:
        if verdict(fp_new, kb) == "violation" and verdict(statefp.read(dest), kb) == "clean":
            return dest.with_name(dest.stem + ".quarantine.state")
    except Exception:  # noqa: BLE001  the gate never decides the run's fate
        pass
    return dest
