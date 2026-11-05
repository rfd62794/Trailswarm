import json
import os

import pytest

from pokeagent.registry import register_worker, unregister_worker


def test_registry_enforces_six_worker_cap(tmp_path, monkeypatch):
    monkeypatch.setattr('pokeagent.registry.process_alive', lambda pid: True)
    path = tmp_path / 'agents.json'
    for port in range(8890, 8896):
        register_worker(path, port, {'tag': str(port)})
    with pytest.raises(RuntimeError, match='cap'):
        register_worker(path, 8896, {'tag': 'extra'})
    assert len(json.loads(path.read_text())) == 6


def test_registry_rejects_duplicate_live_seat(tmp_path, monkeypatch):
    monkeypatch.setattr('pokeagent.registry.process_alive', lambda pid: True)
    path = tmp_path / 'agents.json'
    register_worker(path, 8890, {'tag': 'first'})
    with pytest.raises(FileExistsError):
        register_worker(path, 8890, {'tag': 'duplicate'})
    assert json.loads(path.read_text())['8890']['tag'] == 'first'


def test_old_worker_cannot_unregister_new_owner(tmp_path, monkeypatch):
    path = tmp_path / 'agents.json'
    monkeypatch.setattr('pokeagent.registry.process_alive', lambda pid: False)
    old = register_worker(path, 8890, {'tag': 'old'})
    new = register_worker(path, 8890, {'tag': 'new'})
    unregister_worker(path, 8890, old)
    current = json.loads(path.read_text())['8890']
    assert current['tag'] == 'new' and current['pid'] == os.getpid()
    unregister_worker(path, 8890, new)
    assert json.loads(path.read_text()) == {}


def test_corrupt_registry_fails_closed(tmp_path):
    path = tmp_path / 'agents.json'
    path.write_text('not json')
    with pytest.raises(ValueError):
        register_worker(path, 8890, {'tag': 'unsafe'})
