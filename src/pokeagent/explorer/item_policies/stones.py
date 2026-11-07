"""Evolution stones: use one when a party species evolves with it AND the evolved form is not worse for the next boss matchup.
Shield: never evolve when the evolved form learns a move at this level while the mon has four (the forget prompt could take a move
the party needs: an HM the campaign still wants, or the sole coverage move), and never a Magikarp."""
from __future__ import annotations

from typing import Callable

from pokeagent.explorer.item_policies import ids
from pokeagent.explorer.item_policies.view import MAGIKARP, Mon

Compare = Callable[[Mon, str], "bool | None"]      # (mon, evolved species) -> True not worse / False worse / None cannot tell (None never evolves)
LearnsAt = Callable[[str, int], list]               # (species, level) -> moves learned at exactly that level


def evolve_table(kb: dict | None = None) -> dict[str, list[tuple[str, str]]]:
    """{species: [(stone name, evolved species)]} from the ROM learnset table."""
    from pokeagent.knowledge.kb import table
    return {sp: [(e["item"], e["into"]) for e in row.get("evolves", ()) if e.get("how") == "item"]
            for sp, row in table(kb, "learnsets").items()}


def move_risk(mon: Mon, new_moves: list, needed: set[str]) -> str | None:
    """Why the evolution must not happen, or None. A full moveset + a new move = a forget prompt over moves the party needs."""
    if new_moves and len(mon.moves) >= 4 and needed & set(mon.moves):
        return f"{mon.species} would be asked to forget a move for {new_moves[0]} while holding {sorted(needed & set(mon.moves))}"
    return None


def should_use(*, bag: dict[int, int], party: list[Mon], evolutions: dict[str, list[tuple[str, str]]], needed: dict[int, set[str]],
               compare: Compare, learns_at: LearnsAt) -> tuple[int, int, str] | None:
    """``needed[slot]`` = moves that mon must keep. First allowed (stone, slot) wins; a mon with several stones (EEVEE) takes the first
    one whose evolved form compares as not worse."""
    for mon in sorted(party, key=lambda m: -m.level):
        if mon.species == MAGIKARP:
            continue
        for stone_name, into in evolutions.get(mon.species, ()):
            item = next((i for i, n in ids.STONES.items() if n == stone_name), None)
            if item is None or bag.get(item, 0) <= 0:
                continue
            if move_risk(mon, learns_at(into, mon.level), needed.get(mon.slot, set())):
                continue
            if compare(mon, into) is not True:   # only an explicit 'not worse' evolves; no data = wait
                continue
            return item, mon.slot, f"{mon.species} L{mon.level} evolves into {into} with the {stone_name} (not worse for the next boss)"
    return None
