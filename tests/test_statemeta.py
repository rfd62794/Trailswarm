import json
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.statemeta import describe, read_meta, sidecar, write_state


def test_write_state_records_sidecar_and_legacy_states_are_unlabeled(tmp_path):
    emu = FakeEmulator({0xD35E: 1, 0xD362: 18, 0xD361: 10, 0xD163: 1})
    state = tmp_path / 'viridian_old_man.state'
    meta = write_state(emu, state, source='deliver_parcel_closed.state',
                       segment='to_route2', note='at Viridian Route 2 gate')
    assert state.exists()
    saved = read_meta(state)
    assert saved == meta
    assert saved.game['map_id'] == 1
    assert saved.game['x'] == 18
    assert saved.segment == 'to_route2'
    assert saved.verified
    assert json.loads(sidecar(state).read_text())['source'] == 'deliver_parcel_closed.state'

    legacy = tmp_path / 'legacy.state'
    legacy.write_bytes(b'opaque')
    unlabeled = describe(legacy)
    assert unlabeled['verified'] is False
    assert unlabeled['source'] is None
