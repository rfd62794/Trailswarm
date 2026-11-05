from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import MapMemory


def test_memory_records_paths_interactions_and_npcs(tmp_path):
    mem = MapMemory(tmp_path / 'maps.json')
    assert mem.learn((1, 10, 10), 'UP', (1, 10, 9), confirmed=True) == 'moved'
    assert mem.m(1)['paths']['10,10,UP'] == {'to': [1, 10, 9], 'count': 1}

    entry = mem.interact(1, 18, 10, 'UP', 'PRIVATE PROPERTY',
                         screen='DIALOG', menu='UNKNOWN', outcome='dialog',
                         transition=[13, 9, 71], npc={'pic': 7, 'slot': 1, 'last': [18, 9]})
    assert entry['outcomes']['dialog'] == 1
    assert entry['screens']['DIALOG'] == 1
    assert entry['transitions'] == [[13, 9, 71]]
    assert entry['npc']['pic'] == 7

    emu = FakeEmulator({0xC110: 7, 0xC215: 22, 0xC214: 14})  # slot 1 at (18,10)
    mem.observe_npcs(1, emu, 5)
    npc = mem.npc_at(1, 18, 10)
    assert npc['pic'] == 7
    assert npc['positions'] == {'18,10': 1}
