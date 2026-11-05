import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pokeagent.qmodels import load_model, model_compatible

ROOT = Path(__file__).parents[1]
ROM = ROOT / 'roms/Pokemon Red.gb'
STATE = ROOT / 'baselines/bedroom.state'


@pytest.mark.skipif(not ROM.exists() or not STATE.exists(), reason='Local ROM and checkpoint required')
def test_trainer_save_reload_and_share(tmp_path):
    def run(seed, save, load=None, segment='left_house'):
        command = [sys.executable, str(ROOT / 'tools/rl_train.py'), '--rom', str(ROM),
                   '--state', str(STATE), '--segment', segment, '--episodes', '2',
                   '--max-steps', '2', '--evals', '0', '--seed', str(seed),
                   '--share-every', '1', '--save-q', str(save), '--screen-context',
                   '--combat-context', '--battle-learning', '--double-q', '--n-step', '3']
        if load:
            command += ['--load-q', str(load)]
        return subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)

    first = tmp_path / 'first.json'
    result = run(100, first)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(first.read_text())
    assert load_model(first, payload['schema'], 6)
    second = tmp_path / 'second.json'
    result = run(101, second, first)
    assert result.returncode == 0, result.stdout + result.stderr
    peers = list((tmp_path / 'runs/qshare' / payload['schema']).glob('*.json'))
    assert len(peers) == 2
    assert all(model_compatible(p, payload['schema'], 6) for p in peers)
    result = run(102, tmp_path / 'wrong.json', first, 'potion')
    assert result.returncode != 0
    assert 'schema/task mismatch' in result.stderr


def test_culler_does_not_mix_legacy_or_other_schemas(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('rl_cull_integration', ROOT / 'tools/rl_cull.py')
    cull = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cull)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'runs').mkdir()
    reg = {'8890': {'pid': 11, 'tag': 'a', 'segment': 'battle', 'cmd': ['--segment', 'battle']},
           '8891': {'pid': 12, 'tag': 'b', 'segment': 'battle', 'cmd': ['--segment', 'battle']}}
    (tmp_path / 'runs/rl_agents.json').write_text(json.dumps(reg))
    for port, tag, schema, wins in [('8890', 'a', 'one', 10), ('8891', 'b', 'two', 0)]:
        (tmp_path / f'runs/rlstatus_{port}.json').write_text(json.dumps(
            dict(tag=tag, schema=schema, wins=wins, win_avg=10 if wins else None)))
    monkeypatch.setattr(cull, 'pid_alive', lambda pid: True)
    monkeypatch.setattr(cull.os, 'kill', lambda *args: pytest.fail('Must not kill across schemas'))
    monkeypatch.setattr(cull.subprocess, 'Popen', lambda *args, **kw: pytest.fail('Must not spawn'))
    cull.cull_once()


@pytest.mark.skipif(not ROM.exists() or not STATE.exists(), reason='Local ROM and checkpoint required')
def test_rendering_and_publication_do_not_change_ram():
    spec = importlib.util.spec_from_file_location('rl_env_render_test', ROOT / 'tools/rl_env.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Publisher:
        def publish(self, advance=True):
            assert advance is False

        def close(self):
            pass

    environments = [module.SegmentEnv(ROM, STATE, lambda emu: False, max_steps=40)
                    for _ in range(3)]
    try:
        environments[1].frame_pub = Publisher()
        environments[1].render_interval = 0
        environments[2].frame_pub = Publisher()
        environments[2].publish_frames = True
        for env in environments:
            env.reset()
        for action in [4, 4, 0, 1, 2, 3, 5, 4] * 3:
            for env in environments:
                env.step(action)
                env.publish()
            snapshots = [env.emu.read_range(0xC000, 0x2000) for env in environments]
            assert snapshots[0] == snapshots[1] == snapshots[2]
    finally:
        for env in environments:
            env.close()


@pytest.mark.skipif(not ROM.exists() or not (ROOT / 'baselines/battle.state').exists(),
                    reason='Local battle checkpoint required')
def test_default_hold_and_release_can_finish_battle():
    spec = importlib.util.spec_from_file_location('rl_env_release_test', ROOT / 'tools/rl_env.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = module.SegmentEnv(ROM, ROOT / 'baselines/battle.state', lambda emu: False,
                            goal_name='battle', hold=8, settle=8, max_steps=200)
    env._goal_saved = True
    try:
        env.reset()
        for _ in range(200):
            _, _, done, _ = env.step(4)
            if done:
                break
        assert env.goal_reached
    finally:
        env.close()


@pytest.mark.skipif(not ROM.exists() or not STATE.exists(), reason='Local ROM and checkpoint required')
def test_periodic_evaluation_does_not_change_training(tmp_path):
    def run(directory, interval):
        directory.mkdir()
        model = directory / 'model.json'
        command = [sys.executable, str(ROOT / 'tools/rl_train.py'), '--rom', str(ROM),
                   '--state', str(STATE), '--segment', 'left_house', '--episodes', '2',
                   '--max-steps', '2', '--evals', '0', '--seed', '17', '--save-q', str(model),
                   '--eval-every', str(interval), '--periodic-evals', '1']
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(model.read_text())

    without = run(tmp_path / 'without', 0)
    with_evaluation = run(tmp_path / 'with', 1)
    assert without == with_evaluation
    records = list((tmp_path / 'with/runs/evaluations').glob('*/*.json'))
    assert len(records) == 2
    assert all(json.loads(path.read_text())['epsilon'] == 0 for path in records)
