"""The state guard: a save state is bound to one ROM, even when memory is shared.

``StateMeta.game_key`` in a state's sidecar records which GAME wrote it (the game, not the memory
family: Red and Blue will share memory but never a state). ``check_state_game`` refuses to load a
state labelled for another game, and refuses an unlabeled state - no sidecar, an unreadable sidecar,
or a sidecar without ``game_key`` (every state written before this existed) - for any game that does
not own the legacy paths, because every unlabeled state in the wild is Red's.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.game.spec import GameSpec


class StateGameMismatch(ValueError):
    """A state labelled for another game, or an unlabeled state for a non-legacy game.

    A ``ValueError`` so callers that already catch bad-state ``ValueError`` keep working. ``found``
    is the sidecar's ``game_key`` (``None`` when the state is unlabeled), ``expected`` the loading
    game's key.
    """

    def __init__(self, path: Path, found: str | None, expected: str) -> None:
        self.path, self.found, self.expected = Path(path), found, expected
        if found is None:
            msg = (f"state {self.path} is unlabeled (no game_key in its sidecar): it may belong to "
                   f"another game, refusing to load it under {expected}")
        else:
            msg = f"state {self.path} was written for {found}, refusing to load it under {expected}"
        super().__init__(msg)


def check_state_game(path: Path, game: GameSpec) -> None:
    """Raise ``StateGameMismatch`` unless ``path``'s sidecar allows ``game`` to load it.

    Reads the one key straight from ``<path>.meta.json`` (same shape as ``statemeta.sidecar``);
    importing statemeta here is avoided - it pulls in observations/ram.
    """
    side = Path(path).with_name(Path(path).name + ".meta.json")
    found = None
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        found = data.get("game_key") if isinstance(data, dict) else None
    except (OSError, ValueError):
        pass
    if found == game.key:
        return
    if found is not None:
        raise StateGameMismatch(path, found, game.key)
    if not game.owns_legacy_paths:
        raise StateGameMismatch(path, None, game.key)
