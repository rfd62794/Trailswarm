"""State fingerprints (statefp) stamped beside leg states, and the curriculum refusing ship-stage states whose blackout lands
behind Vermilion (2026-11-07: 8 ship states respawned in Cerulean; 309 ship blackouts sent runs back there)."""
import sys
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import seg_sched  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import checkpoint_goals as cg, statefp  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.explorer.press_frame import PressFrame  # noqa: E402
from pokeagent.legs import states as S  # noqa: E402

LEAD = 0xD16B


def world(respawn=5, hp=79, mx=79, level=29, potions=2):
    """A FakeEmulator standing in map 0x61 (13, 6), one party mon, a potion stack, 1,234 money, two badges."""
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: 1, 0xD164: 179})
    for off, v in ((0, 179), (1, hp >> 8), (2, hp & 255), (33, level), (34, mx >> 8), (35, mx & 255)):
        emu.memory[LEAD + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: potions, 0xD320: 0xFF})
    return emu


def test_fingerprint_reads_the_ram_facts():
    fp = statefp.fingerprint(world(respawn=3, hp=6), source_run="explore-x")
    assert (fp["map"], fp["x"], fp["y"], fp["respawn"], fp["badges"], fp["money"]) == (0x61, 13, 6, 3, 2, 1234)
    assert fp["party"] == [[179, 29, 6, 79]] and fp["heal_items"] == 2 and fp["source_run"] == "explore-x"
    assert round(statefp.party_hp_fraction(fp), 2) == 0.08


def test_fingerprint_never_raises_on_a_minimal_emulator():
    class Bare:
        def read(self, a):
            raise OSError("gone")
    assert statefp.fingerprint(Bare()) == {"v": statefp.VERSION}


def test_stamp_round_trips_beside_the_state(tmp_path):
    p = tmp_path / "a.state"
    statefp.stamp(world(), p)
    assert statefp.sidecar(p).name == "a.state.fp.json" and statefp.read(p)["respawn"] == 5
    assert statefp.read(tmp_path / "missing.state") is None


def _saver_ctx(emu, tmp_path):
    c = SimpleNamespace(emu=emu, run_dir=tmp_path / "explore-7", logs=[])
    c.log = lambda t, tag=None: c.logs.append(t)
    return c


def _frame(a):
    return PressFrame("RIGHT", "agent", "", before=(1, 0, 0), after=a, box_after=False)


def test_leg_saver_stamps_a_fingerprint_and_rotates_it_with_the_state(tmp_path):
    for respawn in (3, 5, 5):
        S.LegStateSaver(tmp_path).observe(_saver_ctx(world(respawn=respawn), tmp_path), _frame((0x61, 13, 6)))
    assert [statefp.read(tmp_path / n)["respawn"] for n in ("97_13_6.state", "97_13_6.1.state", "97_13_6.2.state")] == [5, 5, 3]
    assert statefp.read(tmp_path / "97_13_6.state")["source_run"] == "explore-7"


def test_leg_saver_still_saves_when_the_stamp_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(statefp, "stamp", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    c = _saver_ctx(world(), tmp_path)
    p = S.LegStateSaver(tmp_path).observe(c, _frame((0x61, 13, 6)))
    assert p is not None and p.exists() and "unstamped" in c.logs[0]


def test_evict_drops_the_fingerprint_with_its_state(tmp_path):
    for i in range(6):
        S.LegStateSaver(tmp_path, max_files=4).observe(_saver_ctx(world(), tmp_path), _frame((0x61, i, 6)))
    left = {f.name for f in tmp_path.iterdir()}
    assert all(n.removesuffix(statefp.SUFFIX) in left for n in left if n.endswith(statefp.SUFFIX))


# ---- the curriculum refuses a ship-stage state that respawns behind Vermilion
def _chain(tmp_path, through, respawn, fp_only=False):
    """Checkpoints for every selectable goal up to ``through`` (a sidecar-less legacy chain) except ``through`` itself, which
    carries ``respawn`` (goals sidecar, or only a fingerprint with fp_only)."""
    order = ss.selectable_goals()
    d = tmp_path / "runs/checkpoints"
    d.mkdir(parents=True)
    (tmp_path / "baselines").mkdir()
    (tmp_path / "baselines/bedroom.state").write_bytes(b"s")
    for g in order[:order.index(through) + 1]:
        (d / f"{g}.state").write_bytes(b"s")
    p = d / f"{through}.state"
    if fp_only:
        statefp.write(p, {"v": 1, "respawn": respawn})
    elif respawn is not None:
        cg.write_completed(p, order[:order.index(through) + 1], respawn)
    return order


def test_ship_state_behind_vermilion_is_refused_and_the_frontier_remakes_it(tmp_path):
    order = _chain(tmp_path, "to_ss_anne", 3)
    assert ss.refusal(tmp_path, "to_ss_anne") and not ss.ckpt_valid(tmp_path, "to_ss_anne")
    assert ss.ckpt_valid(tmp_path, "to_vermilion")                       # not a ship stage: Vermilion arrival precedes the heal
    logs = []
    c = seg_sched.Curriculum(tmp_path, log=logs.append)
    assert [s.key for s in c.groups()["frontier"]] == ["to_ss_anne"]
    c.groups()
    assert sum("refusing checkpoint to_ss_anne" in m for m in logs) == 1   # logged once, not per beat


def test_ship_state_respawning_in_vermilion_or_unknown_is_accepted(tmp_path):
    _chain(tmp_path, "to_ss_anne", 5)
    assert ss.refusal(tmp_path, "to_ss_anne") is None and ss.ckpt_valid(tmp_path, "to_ss_anne")
    _chain(tmp_path / "u", "to_ss_anne", None)                           # no record at all: cannot judge
    assert ss.ckpt_valid(tmp_path / "u", "to_ss_anne")


def test_a_fingerprint_alone_is_enough_to_refuse(tmp_path):
    _chain(tmp_path, "to_ss_anne", 3, fp_only=True)
    assert "behind Vermilion" in ss.refusal(tmp_path, "to_ss_anne") and not ss.ckpt_valid(tmp_path, "to_ss_anne")


def test_copy_sidecar_carries_the_fingerprint(tmp_path):
    a, b = tmp_path / "a.state", tmp_path / "b.state"
    statefp.write(a, {"v": 1, "respawn": 5})
    cg.copy_sidecar(a, b)
    assert statefp.read(b) == {"v": 1, "respawn": 5}


def test_stamp_states_tool_stamps_only_the_unstamped(tmp_path):
    import stamp_states
    emu = world(respawn=3)
    a, b = tmp_path / "a.state", tmp_path / "b.state"
    emu.save_state(a)
    emu.save_state(b)
    statefp.write(b, {"v": 1, "respawn": 5})
    assert stamp_states.stamp_all(emu, [a, b]) == [a]
    assert statefp.read(a)["respawn"] == 3 and statefp.read(b)["respawn"] == 5
    assert stamp_states.stamp_all(emu, [a, b], force=True) == [a, b]
