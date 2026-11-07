"""Novelty rewards and the discovery log (see docs/NOVELTY.md in the commit message / tools/novelty.py).

Novelty is measured on GAME STATE only (tiles, maps, warps, event-flag bits, items, species, moves), never on pixels or
text, so menu spam and screen noise earn nothing. Counts are global across the swarm; only explorer-role agents are
steered or rewarded by them. Discoveries (glitch maps, duplicated items, ...) are flagged for review, never rewarded.
"""
