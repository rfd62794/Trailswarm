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
