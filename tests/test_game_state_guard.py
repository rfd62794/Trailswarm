"""check_state_game: a state loads only for the game its sidecar names; unlabeled states are Red's alone."""
import json
from pathlib import Path

import pytest

from pokeagent import cli
from pokeagent.emulator import FakeEmulator
from pokeagent.game import RED
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec
from pokeagent.game.state_guard import StateGameMismatch, check_state_game


def _spec(key, family, owns) -> GameSpec:
    return GameSpec(
        key=key, title=key, rom_sha1=("A" * 40,), default_rom=Path("roms/x.gb"),
        screen=(2, 2), buttons=("a",), memory_family=family, owns_legacy_paths=owns,
    )


SIBLING = _spec("test-sibling", LEGACY_FAMILY, False)   # Red's family, not the legacy owner (Blue stand-in)
OWN = _spec("test-game", "test-game", False)            # its own family


def _state(tmp_path, game_key="__none__", name="s.state"):
    """A state file plus its .meta.json sidecar; game_key=None means an unlabeled sidecar."""
    st = tmp_path / name
    st.write_bytes(b"opaque")
    if game_key != "__none__":
        st.with_name(st.name + ".meta.json").write_text(
            json.dumps({"game_key": game_key}), encoding="utf-8")
    return st


def test_matching_key_loads(tmp_path):
    check_state_game(_state(tmp_path, "pokemon-red"), RED)
    check_state_game(_state(tmp_path, "test-sibling", "t.state"), SIBLING)
    check_state_game(_state(tmp_path, "test-game", "o.state"), OWN)


def test_mismatch_names_both_keys_and_the_path(tmp_path):
    st = _state(tmp_path, "pokemon-red")
    with pytest.raises(StateGameMismatch) as e:
        check_state_game(st, SIBLING)
    msg = str(e.value)
    assert "pokemon-red" in msg and "test-sibling" in msg and str(st) in msg


def test_sibling_cannot_load_reds_state_and_reverse(tmp_path):
    with pytest.raises(StateGameMismatch):
        check_state_game(_state(tmp_path, "pokemon-red"), SIBLING)
    with pytest.raises(StateGameMismatch):
        check_state_game(_state(tmp_path, "test-sibling"), RED)


def test_unlabeled_state_loads_only_for_the_legacy_owner(tmp_path):
    st = tmp_path / "legacy.state"  # no sidecar at all
    st.write_bytes(b"opaque")
    check_state_game(st, RED)
    for game in (SIBLING, OWN):
        with pytest.raises(StateGameMismatch) as e:
            check_state_game(st, game)
        assert "unlabeled" in str(e.value)


def test_sidecar_without_game_key_is_unlabeled(tmp_path):
    st = tmp_path / "old.state"
    st.write_bytes(b"opaque")
    st.with_name(st.name + ".meta.json").write_text('{"map_id": 1}', encoding="utf-8")
    check_state_game(st, RED)
    with pytest.raises(StateGameMismatch):
        check_state_game(st, SIBLING)


def test_unreadable_sidecar_is_unlabeled(tmp_path):
    st = tmp_path / "corrupt.state"
    st.write_bytes(b"opaque")
    st.with_name(st.name + ".meta.json").write_text("{not json", encoding="utf-8")
    check_state_game(st, RED)
    with pytest.raises(StateGameMismatch):
        check_state_game(st, OWN)


def test_mismatch_is_a_value_error():
    assert issubclass(StateGameMismatch, ValueError)


def test_run_refuses_a_state_labeled_for_another_game(tmp_path, monkeypatch, capsys):
    """cli.py's load path gets the refusal as 'error: <msg>', exit 2 - no traceback."""
    fake = FakeEmulator()
    monkeypatch.setattr(cli, "_build_emulator", lambda args: fake)
    st = _state(tmp_path, "other-game")
    rc = cli.main(["run", "--steps", "1", "--runs-dir", str(tmp_path / "runs"), "--state", str(st)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "error:" in out and "other-game" in out and "pokemon-red" in out
    assert fake.closed
