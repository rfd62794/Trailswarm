"""The state ledger (statelog) choosing resume points, its consumers (seg_store.ckpt, attach.plan), and the
``pokeagent states`` CLI - 2026-11-07: the swarm ran the captain segment from a Cerulean-respawn state at 6/79 HP
while a Vermilion-respawn full-HP state sat on the same tile, because nothing could choose it."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import seg_store as ss  # noqa: E402
from pokeagent import checkpoint_goals as cg, statefp, statelog, statescmd  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.legs import attach  # noqa: E402

LEAD = 0xD16B


def world(respawn=5, hp=79, mx=79, level=29, potions=2, map_id=0x61):
    """A FakeEmulator standing in ``map_id`` (13, 6), one party mon, a potion stack, 1,234 money, two badges."""
    emu = FakeEmulator({0xD35E: map_id, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: 1, 0xD164: 179})
    for off, v in ((0, 179), (1, hp >> 8), (2, hp & 255), (33, level), (34, mx >> 8), (35, mx & 255)):
        emu.memory[LEAD + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: potions, 0xD320: 0xFF})
    return emu


def saved(d, name, emu, mtime=1000.0):
    """Write a state and its fingerprint sidecar; ``mtime`` controls the age select ranks on."""
    p = d / name
    emu.save_state(p)
    statefp.stamp(emu, p)
    os.utime(p, (mtime, mtime))
    return p


def test_select_prefers_respawn_ahead_over_newer(tmp_path):
    saved(tmp_path, "ss_anne_captain.state", world(respawn=3), mtime=2000)       # newer, respawns in Cerulean
    good = saved(tmp_path, "ss_anne_captain@63.state", world(respawn=5), 1000)  # older, respawns in Vermilion
    es = statelog.entries(tmp_path)
    assert statelog.select(es, statelog.Want(stem="ss_anne_captain", respawn_ahead_of=5)).path == good
    assert statelog.select(es, statelog.Want(stem="ss_anne_captain")).path.name == "ss_anne_captain.state"  # no filter: newest
    assert statelog.pick(tmp_path, statelog.Want(stem="ss_anne_captain", respawn_ahead_of=5)) == good


def test_min_hp_filters_and_a_missing_key_fails(tmp_path):
    hurt = saved(tmp_path, "a.state", world(hp=6, mx=79), 2000)
    well = saved(tmp_path, "b.state", world(hp=79), 1000)
    bare = tmp_path / "c.state"                                       # fingerprint without a "party" key, freshest
    bare.write_bytes(b"x")
    statefp.write(bare, {"v": 1, "map": 0x61})
    os.utime(bare, (3000, 3000))
    es = statelog.entries(tmp_path)
    assert statelog.select(es, statelog.Want(min_hp=0.5)).path == well        # 6/79 is below half; c.state cannot prove HP
    assert statelog.select(es, statelog.Want(min_hp=0.05)).path == hurt       # 6/79 qualifies; c.state still cannot
    assert statelog.select(es, statelog.Want()).path == bare                  # unfiltered: the fresh newest wins
    assert statelog.pick(tmp_path, statelog.Want(min_hp=0.5)) == well


def test_strongest_prefers_power_then_newest(tmp_path):
    strong = saved(tmp_path, "s.state", world(level=29, hp=79), 1000)          # power 29
    saved(tmp_path, "w.state", world(level=10, hp=79), 3000)                   # power 10, newest
    es = statelog.entries(tmp_path)
    assert statelog.select(es, statelog.Want()).path.name == "w.state"         # default: newest wins
    assert statelog.select(es, statelog.Want(strongest=True)).path == strong   # power first
    strong2 = saved(tmp_path, "s2.state", world(level=29, hp=79), 2000)        # equal power, newer than s
    assert statelog.select(statelog.entries(tmp_path), statelog.Want(strongest=True)).path == strong2


def test_unstamped_and_v0_states_are_stale_and_never_selected(tmp_path):
    (tmp_path / "n.state").write_bytes(b"x")                                   # no sidecar
    stale = tmp_path / "o.state"
    stale.write_bytes(b"x")
    statefp.write(stale, {"v": 0, "respawn": 5})                               # v older than the reader
    es = statelog.entries(tmp_path)
    assert [statelog.status(e) for e in es] == ["stale", "stale"]
    assert statelog.select(es, statelog.Want()) is None
    assert statelog.select([], statelog.Want()) is None                        # nothing to choose from
    assert statelog.entries(tmp_path / "missing") == []                        # a missing dir reads as empty
    assert statelog.pick(tmp_path, statelog.Want()) is None


def test_retire_moves_state_and_sidecars_and_logs(tmp_path):
    p = saved(tmp_path, "x.state", world(respawn=3))
    cg.write_completed(p, ["to_vermilion"], respawn=3)
    dest = statelog.retire(p, "respawns in Cerulean", retired_dir=tmp_path / "retired")
    assert dest == tmp_path / "retired" / "x.state" and dest.exists()
    assert (tmp_path / "retired" / "x.state.fp.json").exists()
    assert (tmp_path / "retired" / "x.state.goals.json").exists()
    assert not p.exists() and not statefp.sidecar(p).exists() and not cg.sidecar(p).exists()
    assert (tmp_path / "retired" / "RETIRED.log").read_text().strip().split("\t")[1:] == ["x.state", "respawns in Cerulean"]
    with pytest.raises(ValueError):
        statelog.retire(p, "")


def test_seg_store_ckpt_uses_the_ledger_first(tmp_path):
    d = tmp_path / "runs" / "checkpoints"
    d.mkdir(parents=True)
    saved(d, "ss_anne_captain.state", world(respawn=3), 2000)                  # behind Vermilion: the bad ancestor
    good = saved(d, "ss_anne_captain@63.state", world(respawn=5), 1000)        # the state the ledger should choose
    assert ss.ckpt(tmp_path, "ss_anne_captain") == good
    only_bad = saved(d, "ss_anne_2f.state", world(respawn=3), 1500)
    assert ss.ckpt(tmp_path, "ss_anne_2f") == only_bad       # nothing qualifies: the old name/mtime path stands
    old = d / "to_vermilion.state"
    old.write_bytes(b"x")                                                     # unstamped: the ledger never sees it
    assert ss.ckpt(tmp_path, "to_vermilion") == old
    assert ss.ckpt(tmp_path, "nope") is None


def test_attach_plan_prefers_a_healthy_rotation_and_falls_back(tmp_path, monkeypatch):
    sd = tmp_path / "states"
    sd.mkdir()
    hurt = saved(sd, "5_2_2.state", world(hp=6, mx=79, map_id=5), 2000)        # base file: 6/79 HP
    good = saved(sd, "5_2_2.1.state", world(hp=79, map_id=5), 1000)            # rotation: full HP, older
    monkeypatch.setattr(attach.D, "par_frames_for", lambda spec, rom: 64.0)    # no ROM in the worktree
    pl = attach.plan("5:2,2->4,2", None, 600, sd, None, min_hp=0.5)
    assert pl.kind == "leg" and pl.state == good
    pl = attach.plan(None, 5, 600, sd, None, min_hp=0.5)
    assert pl.kind == "grind" and pl.state == good                             # grind drills pick by map the same way
    pl = attach.plan(None, 5, 600, sd, None)
    assert pl.state == hurt                                                    # min_hp 0: newest fresh = newest_on_map
    sd2 = tmp_path / "hurt_only"
    sd2.mkdir()
    saved(sd2, "5_2_2.state", world(hp=6, mx=79, map_id=5), 2000)
    pl = attach.plan(None, 5, 600, sd2, None, min_hp=0.5)
    assert pl.state == sd2 / "5_2_2.state"                                     # nothing qualifies: the old pick stands
    sd3 = tmp_path / "bare"
    sd3.mkdir()
    old = sd3 / "5_2_2.state"
    old.write_bytes(b"x")
    pl = attach.plan(None, 5, 600, sd3, None, min_hp=0.5)
    assert pl.state == old                                                     # unstamped states stay on the old path


def test_states_cli_list_bad_check_and_retire(tmp_path, capsys, monkeypatch):
    saved(tmp_path, "ok.state", world(respawn=5))
    saved(tmp_path, "to_ss_anne.state", world(respawn=3))                      # ship checkpoint behind Vermilion
    (tmp_path / "other.state").write_bytes(b"x")                               # no sidecar: listed, not a ship failure

    assert statescmd.cmd_list(SimpleNamespace(dir=[str(tmp_path)], map=None, bad=True)) == 0
    out = capsys.readouterr().out
    assert "to_ss_anne.state" in out and "behind Vermilion" in out
    assert "other.state" in out and "ok.state" not in out

    assert statescmd.cmd_check(SimpleNamespace(dir=[str(tmp_path)])) == 1      # a ship state respawns behind Vermilion
    assert "to_ss_anne.state" in capsys.readouterr().out

    clean = tmp_path / "clean"
    clean.mkdir()
    saved(clean, "to_ss_anne.state", world(respawn=5))
    (clean / "other.state").write_bytes(b"x")                                  # non-ship unstamped: listed, exits 0
    assert statescmd.cmd_check(SimpleNamespace(dir=[str(clean)])) == 0
    assert "other.state" in capsys.readouterr().out

    monkeypatch.chdir(tmp_path)
    victim = tmp_path / "retire_me.state"
    victim.write_bytes(b"x")
    assert statescmd.cmd_retire(SimpleNamespace(path=victim, why="superseded")) == 0
    assert (tmp_path / "runs" / "retired" / "retire_me.state").exists() and not victim.exists()
    assert "retire_me.state" in capsys.readouterr().out


def test_states_cli_restamp_dry_run(tmp_path, capsys):
    (tmp_path / "x.state").write_bytes(b"x")
    assert statescmd.cmd_restamp(SimpleNamespace(dir=[str(tmp_path)], force=False, dry_run=True)) == 0
    assert "x.state" in capsys.readouterr().out


def test_states_help_renders(capsys):
    """argparse formats every help string; a bare % in one (HP%) crashed `pokeagent states --help`."""
    from pokeagent.cli import _build_parser
    with pytest.raises(SystemExit) as exc:
        _build_parser().parse_args(["states", "--help"])
    assert exc.value.code == 0
    assert "HP%" in capsys.readouterr().out


def test_select_skips_malformed_sidecars(tmp_path):
    """Corrupt-but-valid-JSON fingerprints are stale or non-matching; select never raises on them."""
    good = saved(tmp_path, "g.state", world(hp=79), 1000)
    for name, mutate in (
        ("v_str.state", lambda fp: fp.update(v="1")),                       # v as a string: stale
        ("party_str.state", lambda fp: fp.update(party="abc")),             # party as a string
        ("party_short.state", lambda fp: fp.update(party=[[1, 2]])),        # party rows too short
    ):
        p = saved(tmp_path, name, world(hp=79), 3000)                       # newest: would win if it were kept
        fp = statefp.read(p)
        mutate(fp)
        statefp.write(p, fp)
    es = statelog.entries(tmp_path)
    for want in (statelog.Want(), statelog.Want(strongest=True), statelog.Want(min_hp=0.5),
                 statelog.Want(min_lead_level=1, strongest=True)):
        assert statelog.select(es, want).path == good
    only_bad = [e for e in es if e.path.name != "g.state"]
    assert statelog.select(only_bad, statelog.Want(strongest=True, min_hp=0.5)) is None
    assert statelog.pick(tmp_path, statelog.Want(strongest=True, min_hp=0.5)) == good
    for e in es:
        statelog.bad(e)                                                     # reports, never raises
    assert statescmd.cmd_list(SimpleNamespace(dir=[str(tmp_path)], map=None, bad=True)) == 0


def test_synthetic_candidate_is_never_selected(tmp_path):
    real = saved(tmp_path, "r.state", world(hp=79), 1000)
    edited = saved(tmp_path, "e.state", world(hp=79), 3000)                 # newer, and edited by hand
    fp = statefp.read(edited)
    fp["synthetic"] = True
    statefp.write(edited, fp)
    es = statelog.entries(tmp_path)
    assert statelog.select(es, statelog.Want()).path == real
    assert statelog.pick(tmp_path, statelog.Want()) == real
    assert statelog.select([e for e in es if e.path == edited], statelog.Want()) is None


def test_retire_never_overwrites_a_same_named_state(tmp_path, monkeypatch):
    rdir = tmp_path / "retired"
    a = saved(tmp_path, "a.state", world(respawn=5))
    a.write_bytes(b"first")
    first = statelog.retire(a, "one", retired_dir=rdir)
    a2 = saved(tmp_path, "a.state", world(respawn=3))
    a2.write_bytes(b"second")
    second = statelog.retire(a2, "two", retired_dir=rdir)
    assert first == rdir / "a.state" and second != first
    assert first.read_bytes() == b"first" and second.read_bytes() == b"second"
    assert second.name.startswith("a.") and second.name.endswith(".state") and second.name != "a.state"
    assert (rdir / (second.name + statefp.SUFFIX)).exists()                  # its sidecar shares the suffix
    assert (rdir / "a.state.fp.json").exists()                               # the first one's sidecar survives too
    assert len(list(rdir.glob("a*.state"))) == 2


def test_retire_missing_path_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert statescmd.cmd_retire(SimpleNamespace(path=tmp_path / "nope.state", why="x")) == 1
    assert "no such state" in capsys.readouterr().err
    assert not (tmp_path / "runs" / "retired").exists()
    with pytest.raises(FileNotFoundError):
        statelog.retire(tmp_path / "nope.state", "x", retired_dir=tmp_path / "r")


def test_huge_int_party_and_deep_sidecar_never_raise(tmp_path):
    """json accepts a 400-digit int: party_hp_fraction/_power then raise OverflowError, and a deeply nested sidecar
    raises RecursionError in json.loads. Both must degrade to stale/unreadable, never escape select or pick."""
    good = saved(tmp_path, "g.state", world(hp=79), 1000)
    huge = saved(tmp_path, "h.state", world(hp=79), 3000)                    # newest: would win if kept
    fp = statefp.read(huge)
    fp.update(party=[[1, 10 ** 400, 1, 1]])
    statefp.write(huge, fp)
    es = statelog.entries(tmp_path)
    assert statelog.status(next(e for e in es if e.path == huge)) == "stale"
    for want in (statelog.Want(), statelog.Want(strongest=True), statelog.Want(min_hp=0.5)):
        assert statelog.select(es, want).path == good
        assert statelog.pick(tmp_path, want) == good
    deep = saved(tmp_path, "d.state", world(hp=79), 4000)
    statefp.sidecar(deep).write_text("[" * 200000, encoding="utf-8")          # RecursionError inside json.loads
    assert statefp.read(deep) is None
    assert statelog.select(statelog.entries(tmp_path), statelog.Want()).path == good
