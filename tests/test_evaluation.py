from collections import defaultdict
import importlib.util
from pathlib import Path
import random
import sys
from types import SimpleNamespace

import pytest

from pokeagent.evaluation import evaluate_table, exploration_rate


def test_exploration_schedule_does_not_depend_on_run_length():
    assert exploration_rate(0, 100, 0.1) == 1
    assert exploration_rate(50, 100, 0.1) == 0.5
    assert exploration_rate(500, 100, 0.1) == 0.1
    with pytest.raises(ValueError):
        exploration_rate(0, 0, 0.1)


def test_evaluation_respects_mask_and_leaves_table_and_rng_unchanged(tmp_path):
    source = tmp_path / 'state'
    source.write_bytes(b'checkpoint')
    closed = []

    class Environment:
        max_steps = 2

        def reset(self):
            self.steps = 0
            self.goal_reached = False
            return (999,)

        def allowed_actions(self):
            return [1]

        def step(self, action):
            assert action == 1
            self.steps += 1
            self.goal_reached = True
            return (1000,), 1, True, {'outcome': 'win'}

        def close(self):
            closed.append(True)

    table = defaultdict(lambda: [0.0, 0.0], {(1,): [100, -100]})
    before = dict(table)
    rng_before = random.getstate()
    result = evaluate_table(lambda state: Environment(), table, [source], 3, 'schema')
    assert result['wins'] == 3
    assert result['mean_solved_steps'] == 1
    assert result['epsilon'] == 0
    assert result['evaluation_scope'] == 'fixed_checkpoint_greedy'
    assert len(closed) == 3
    assert dict(table) == before
    assert random.getstate() == rng_before


def test_evaluation_marks_multiple_start_states(tmp_path):
    states = []
    for name in ('a', 'b'):
        path = tmp_path / name
        path.write_bytes(name.encode())
        states.append(path)

    class Environment:
        max_steps = 1
        goal_reached = True
        steps = 1

        def reset(self):
            return (1,)

        def allowed_actions(self):
            return [0]

        def step(self, action):
            return (2,), 1, True, {'outcome': 'win'}

        def close(self):
            pass

    result = evaluate_table(lambda state: Environment(), {(1,): [1.0]}, states, 4, 'schema')
    assert result['evaluation_scope'] == 'multi_checkpoint'
    assert result['episodes'] == 4
    assert {row['source_state'] for row in result['rollouts']} == {str(states[0]), str(states[1])}


def test_evaluation_closes_environment_on_failure(tmp_path):
    source = tmp_path / 'state'
    source.write_bytes(b'checkpoint')
    closed = []

    class Environment:
        def reset(self):
            raise ValueError('Bad checkpoint')

        def close(self):
            closed.append(True)

    with pytest.raises(ValueError, match='Bad checkpoint'):
        evaluate_table(lambda state: Environment(), {}, [source], 1, 'schema')
    assert closed == [True]


def test_viewer_distinguishes_unevaluated_and_evaluated_policies():
    spec = importlib.util.spec_from_file_location('watch_eval_test', Path(__file__).parents[1] / 'tools/watch.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    agent = SimpleNamespace(ok=True, port=8890, status={'_rl': True, 'tag': 'battle'})
    assert 'EVAL not run' in module.status_line(agent)
    agent.status.update(epsilon=0.25, evaluation={'wins': 2, 'episodes': 3})
    line = module.status_line(agent)
    assert 'EVAL 2/3 greedy' in line
    assert 'eps 0.25' in line
