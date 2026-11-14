"""Group position-log rows into per-NPC tracks keyed (run, area, ident), frame-ordered. Pure."""
from __future__ import annotations


def tracks_from_rows(rows) -> dict:
    """``{(run, area, ident): [{"f","x","y","move","label"}, ...]}`` sorted by frame.

    ``rows`` are ``iter_positions`` dicts; every ent is ``[ident, label, x, y, move]``.
    Areas never mix: ``area`` is part of the key, so the same ``ident`` on two maps is two
    tracks."""
    tracks: dict = {}
    for row in rows:
        for ent in row["ents"]:
            ident, label, x, y, move = ent
            key = (row["run"], row["area"], ident)
            tracks.setdefault(key, []).append(
                {"f": row["f"], "x": x, "y": y, "move": move, "label": label})
    for track in tracks.values():
        track.sort(key=lambda r: r["f"])
    return tracks


def make_track(pos, move: int = 0xFE, label: int = 0, start: int = 0, step: int = 8) -> list:
    """A track in the ``tracks_from_rows`` row shape from ``[(x, y), ...]``."""
    return [{"f": start + i * step, "x": x, "y": y, "move": move, "label": label}
            for i, (x, y) in enumerate(pos)]


def positions(track) -> list:
    """``[(x, y), ...]`` in frame order."""
    return [(r["x"], r["y"]) for r in track]


def collapse(track) -> list:
    """``[(x, y, dwell), ...]``: consecutive same-tile rows merged; dwell is the row count."""
    out: list = []
    for r in track:
        if out and out[-1][0] == r["x"] and out[-1][1] == r["y"]:
            out[-1] = (r["x"], r["y"], out[-1][2] + 1)
        else:
            out.append((r["x"], r["y"], 1))
    return out


def distinct_tiles(track) -> set:
    """The set of ``(x, y)`` tiles the track touched."""
    return {(r["x"], r["y"]) for r in track}


def dwell_at(track, i: int) -> int:
    """Rows spent on the tile at index ``i``, counting ``i`` and its same-tile predecessors."""
    x, y = track[i]["x"], track[i]["y"]
    n = 0
    while i - n >= 0 and track[i - n]["x"] == x and track[i - n]["y"] == y:
        n += 1
    return n
