"""NEVER_CATCH: a wild KAKUNA (Harden only) is never worth a ball; WEEDLE still is (Robert, 2026-11-14)."""
from pokeagent.explorer import catch_list
from pokeagent.explorer.catch_list import catch_wanted


def test_kakuna_is_never_wanted_even_for_the_dex_or_a_plan(monkeypatch):
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    assert catch_wanted("KAKUNA", [], 3, ["dex10"]) is None
    assert catch_wanted("KAKUNA", [], 3, ["dex10"], wants={"KAKUNA": "planned: bench"}) is None


def test_weedle_is_still_wanted_for_the_dex(monkeypatch):
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    assert catch_wanted("WEEDLE", [], 3, ["dex10"]) is not None
