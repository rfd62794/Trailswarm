import importlib.util
import json
import os
from pathlib import Path

import pytest

from pokeagent.learning import BattleOutcome, BattleSample, BattleTracker, battle_reward, potential_reward, retreat_allowed
from pokeagent.observations import SpatialObserver, schema_id
from pokeagent.qmodels import atomic_json, load_model, mean_tables, save_model
from pokeagent.curriculum import mastered


def sample(kind=1, hp=10, maximum=10, party=15, position=(12, 1, 1)):
    return BattleSample(kind, position, hp, maximum, party)


def test_wild_win_once_and_no_initial_zero_false_win():
    tracker = BattleTracker()
    tracker.update(sample(hp=10))
    tracker.update(sample(hp=0))
    assert tracker.update(sample(kind=0)) == BattleOutcome.WIN
    assert tracker.update(sample(kind=0)) == BattleOutcome.NONE
    assert tracker.wild_wins == 1
    tracker.reset()
    tracker.update(sample(hp=0))
    assert tracker.update(sample(kind=0)) == BattleOutcome.DISENGAGED
    assert tracker.wild_wins == 0


def test_retreat_capture_uncertainty_blackout_and_trainer_not_a_wild_win():
    tracker = BattleTracker()
    tracker.update(sample())
    assert tracker.update(sample(kind=0)) == BattleOutcome.DISENGAGED
    tracker.update(sample())
    assert tracker.update(sample(kind=0, party=0)) == BattleOutcome.BLACKOUT
    tracker.update(sample(kind=2))
    tracker.update(sample(kind=2, hp=0))
    assert tracker.update(sample(kind=0)) != BattleOutcome.WIN
    assert battle_reward(BattleOutcome.DISENGAGED, safe_to_fight=True) == 0
    assert battle_reward(BattleOutcome.BLACKOUT, safe_to_fight=True) < 0


def test_blackout_is_latched_before_automatic_healing():
    tracker = BattleTracker()
    tracker.update(sample(party=10))
    tracker.update(sample(party=0))
    healed_after_warp = sample(kind=0, party=15, position=(0, 5, 5))
    assert tracker.update(healed_after_warp) == BattleOutcome.BLACKOUT
    assert tracker.wild_wins == 0


def test_retreat_only_for_explicit_priority_or_low_health():
    assert not retreat_allowed(80, 100)
    assert retreat_allowed(25, 100)
    assert retreat_allowed(80, 100, True)


def test_potential_terminal_and_telescoping():
    gamma = 0.99
    a = potential_reward(-3, -2, gamma, False)
    b = potential_reward(-2, -1, gamma, True)
    assert a + gamma*b == pytest.approx(3)


def test_models_reject_legacy_and_schema_mismatch(tmp_path):
    path = tmp_path / 'q.json'
    save_model(path, {'(1, 2)': [1.0, 2.0]}, 'schema-a', 2)
    assert load_model(path, 'schema-a', 2) == {(1, 2): [1.0, 2.0]}
    with pytest.raises(ValueError):
        load_model(path, 'schema-b', 2)
    path.write_text(json.dumps({'(1, 2)': [1, 2]}))
    with pytest.raises(ValueError):
        load_model(path, 'schema-a', 2)
    assert schema_id('potion') != schema_id('battle')
    assert schema_id('potion') != schema_id('potion', screen=True)
    assert mean_tables([{(1,): [1, 3]}, {(1,): [3, 1]}]) == {(1,): [2, 2]}


def test_atomic_json_retries_transient_windows_sharing_errors(tmp_path, monkeypatch):
    import pokeagent.qmodels as qmodels
    original = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(dst)
        if len(calls) <= 2:
            error = PermissionError('sharing violation')
            error.winerror = 32
            raise error
        return original(src, dst)

    monkeypatch.setattr(qmodels.os, 'replace', flaky_replace)
    target = tmp_path / 'model.json'
    atomic_json(target, {'ok': True})
    assert json.loads(target.read_text()) == {'ok': True}
    assert len(calls) == 3


def test_spatial_unknown_and_obscured(tmp_path):
    path = tmp_path / 'maps.json'
    path.write_text(json.dumps({'tile_types': {'0': {'01,01,01,01': {'solid': 0, 'walkable': 3}}}}))
    observer = SpatialObserver(path)
    assert observer.observe(bytes([1])*360, 1, 0, 0, 0) == (1,)*9 + (0,)
    assert observer.observe(bytes([1])*360, 1, 0, 0, 0, obscured=True) == (0,)*10


def test_checkpoint_is_not_mastery():
    assert not mastered({'episodes': 100, 'wins': 100}, segment='potion')
    record = dict(version=2, success_definition=2, episodes=24, wins=23,
                  segment='potion', schema='abc', epsilon=0, git_sha='sha',
                  model_digest='model', source_digest='source')
    assert mastered(record, segment='potion', schema='abc')
    assert not mastered(record, segment='battle')


def test_directed_warp_distance():
    spec = importlib.util.spec_from_file_location('navgrid_test', Path(__file__).parents[1] / 'tools/navgrid.py')
    nav = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nav)
    grids = {1: {'tiles': {(0, 0)}, 'blocked': set(), 'warps': {(0, 0, 'UP'): (2, 0, 0)}},
             2: {'tiles': {(0, 0)}, 'blocked': set(), 'warps': {}}}
    assert nav.optimal_steps(grids, (1, 0, 0), [('map', 2)]) == 1
    assert nav.optimal_steps(grids, (2, 0, 0), [('map', 1)]) is None
