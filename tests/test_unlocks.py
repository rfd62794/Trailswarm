"""unlocks.capabilities (Cut from RAM) and agent_capabilities (env + RAM + the cut_taught checkpoint evidence)."""
from __future__ import annotations

from pokeagent import campaign, unlocks
from pokeagent.emulator import FakeEmulator

# Offsets of tests/test_campaign.py::test_party_move_detector_reads_every_member_and_slot:
# wPartyCount 0xD163, wPartyMon1Moves 0xD173, 44-byte party struct, 4 move slots each.


def test_capabilities_reads_the_party_moves():
    assert unlocks.capabilities(FakeEmulator({0xD163: 2, 0xD173 + 0x2C + 3: 15})) == {"cut"}   # slot 4 of the second member
    assert unlocks.capabilities(FakeEmulator({0xD163: 2})) == frozenset()                       # nobody knows CUT
    assert unlocks.capabilities(FakeEmulator({0xD163: 1, 0xD173 + 0x2C: 15})) == frozenset()    # a bench slot past the party count


def test_capabilities_never_raises():
    assert unlocks.capabilities(object()) == frozenset()                                      # a failing read answers the empty set


def test_agent_capabilities_env_ram_and_checkpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_CAPS", raising=False)
    caps = campaign.agent_capabilities(root=tmp_path)
    assert caps == frozenset() and isinstance(caps, frozenset)
    assert campaign.agent_capabilities(emu=FakeEmulator({0xD163: 1, 0xD173: 15}), root=tmp_path) == {"cut"}
    (tmp_path / "runs" / "checkpoints").mkdir(parents=True)
    (tmp_path / "runs" / "checkpoints" / "cut_taught.state").write_text("{}")
    assert campaign.agent_capabilities(root=tmp_path) == {"cut"}                              # the curriculum's evidence
    monkeypatch.setenv("POKEAGENT_CAPS", "puzzle")
    assert campaign.agent_capabilities(root=tmp_path) == {"cut", "puzzle"}                    # the union still honours env


def test_cut_checkpoint_unlocks_the_gated_prefix_only(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEAGENT_CAPS", raising=False)
    assert not campaign.selectable("vermilion_gym_entry", campaign.agent_capabilities(root=tmp_path))
    (tmp_path / "runs" / "checkpoints").mkdir(parents=True)
    (tmp_path / "runs" / "checkpoints" / "cut_taught.state").write_text("{}")
    caps = campaign.agent_capabilities(root=tmp_path)
    assert campaign.selectable("vermilion_gym_entry", caps)      # its chain prefix needs only cut
    assert not campaign.selectable("beat_surge", caps)           # it also needs puzzle: stays walled
