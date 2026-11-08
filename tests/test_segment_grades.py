"""segment_grades: solved/optimized/stale/broken/held flags, health, event rates, par."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import seg_hold  # noqa: E402
import seg_store as ss  # noqa: E402
from pokeagent import checkpoint_goals as cg  # noqa: E402
from pokeagent import segment_grades as sg  # noqa: E402
from pokeagent import statefp  # noqa: E402
from test_segment_curriculum import att  # noqa: E402

NOW = 1_800_000_000.0


def seg(doc, key="potion"):
    return next(s for s in ss.layout(doc) if s.key == key)


def st_for(doc, key="potion"):
    return ss.stat(doc, key)


def grade(doc, key="potion", par=None, hold=None, now=NOW):
    return sg.grade_segment(seg(doc, key), st_for(doc, key), ss.FRAMES_PER_STEP, par, now, hold=hold)


def test_solved_via_is_solved():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = [att(True)] * 18 + [att(False)] * 2
    st["n"], st["solves"] = 20, 18
    g = grade(doc)
    assert g.solved and g.rate == 0.9 and g.attempts == 20


def test_optimized_needs_confirmed_best_within_par_tolerance():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = [att(True, frames=1000)] * 20
    st["n"], st["solves"] = 20, 20
    st["confirmed"] = st["best"] = {"frames": 1000, "steps": 10, "run": "r"}
    assert grade(doc, par=1100).optimized              # 1000 <= 1100 * 1.15
    assert not grade(doc, par=850).optimized           # 1000 > 850 * 1.15
    st["confirmed"] = None                             # unconfirmed best is never optimized
    assert not grade(doc, par=1100).optimized


def test_plateau_fallback_without_par():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = [att(True, frames=1000, run="best")] + [att(True, frames=1000)] * 19
    st["n"], st["solves"] = 20, 20
    st["confirmed"] = st["best"] = {"frames": 1000, "steps": 10, "run": "best"}
    g = grade(doc)
    assert g.optimized                                 # 19 solves since, none beat it by > 1%
    st["attempts"][-1]["frames"] = 985                 # a >1% improvement since the best: not plateaued
    assert not grade(doc).optimized
    st["attempts"] = st["attempts"][:10]               # too few solves since the best: not optimized
    st["n"], st["solves"] = 10, 10
    assert not grade(doc).optimized


def test_stale_by_ts_and_by_run_name():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = [att(True, ts=NOW - 4 * 86400)]
    st["n"] = 1
    assert grade(doc).stale                            # newest attempt older than STALE_DAYS
    st["attempts"] = [att(True, ts=NOW - 3600)]
    assert not grade(doc).stale
    st["attempts"] = [att(True, run="explore-19990101-000000-1")]
    assert grade(doc).stale                            # old run name, no ts field
    st["attempts"] = [att(True)]
    assert grade(doc).stale                            # no ts anywhere = stale


def test_broken_by_git_sha_split():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = [att(True, git_sha="aaa")] * 15 + [att(False, git_sha="bbb")] * 5
    st["n"] = 20
    g = grade(doc)
    assert g.broken and g.sha_before == 1.0 and g.sha_after == 0.0
    st["attempts"] = [att(True, git_sha="aaa")] * 16 + [att(False, git_sha="bbb")] * 4
    g = grade(doc)
    assert not g.broken and g.sha_after is None            # too few attempts with the newest sha
    st["attempts"] = [att(True)] * 15 + [att(False)] * 5   # no git_sha: never guessed
    assert not grade(doc).broken


def test_held_from_hold_file(tmp_path):
    doc = ss.empty_doc()
    root = tmp_path
    (root / "runs").mkdir()
    from datetime import datetime
    until = datetime(2030, 1, 1).astimezone()
    seg_hold.write_file(seg_hold.path(root), [seg_hold.Hold("potion", until.isoformat(), until, "fix pending")])
    grades = sg.grade_all(doc, root, NOW, hold_file=seg_hold.HoldFile(root))
    assert grades[0].key == "potion" and grades[0].held == "fix pending"
    assert sg.grade_all(ss.empty_doc(), root, NOW)[0].held is None


def test_health_and_event_rates():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = ([att(True, frames=800, blackouts=0, stalled=False, loops=0)]
                      + [att(True, frames=800, blackouts=2, stalled=True, loops=3)] * 19)
    st["n"], st["solves"] = 20, 20
    st["best"] = {"frames": 800, "steps": 10}
    g = grade(doc)
    assert g.health is not None and g.blackout_rate == 0.95 and g.stall_rate == 0.95 and g.loop_rate == 0.95
    st["attempts"] = [att(True, frames=800)] * 20       # fields absent -> unknown, never guessed
    g = grade(doc)
    assert g.blackout_rate is None and g.stall_rate is None and g.loop_rate is None


def test_event_rates_mean_over_attempts_carrying_the_field():
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"] = ([att(True, frames=800)] * 10                          # old attempts: no field
                      + [att(True, frames=800, blackouts=1, stalled=True, loops=0)] * 5
                      + [att(True, frames=800, blackouts=0, stalled=False, loops=1)] * 5)
    st["n"], st["solves"] = 20, 20
    g = grade(doc)
    assert g.blackout_rate == 0.5 and g.stall_rate == 0.5 and g.loop_rate == 0.5   # the 10 carriers, not all-or-nothing


def test_par_fn_failure_is_logged_once_per_distinct_message(tmp_path, caplog):
    doc = ss.empty_doc()
    st = st_for(doc)
    st["attempts"], st["n"], st["solves"] = [att(True)] * 20, 20, 20

    def boom(seg, st):
        raise ValueError("no par today")

    sg._logged.clear()   # module-level seen-set: do not inherit messages from earlier tests
    with caplog.at_level(logging.WARNING, logger="pokeagent.segment_grades"):
        for _ in range(2):
            grades = sg.grade_all(doc, tmp_path, NOW, par_fn=boom)
            assert all(g.par is None for g in grades)              # fallback behaviour kept
    assert sum("par_fn failed: ValueError: no par today" in r.message for r in caplog.records) == 1


def test_start_grade_ok_missing_refusal(tmp_path):
    root = tmp_path
    (root / "baselines").mkdir()
    (root / "baselines/bedroom.state").write_bytes(b"s")
    s = seg(ss.empty_doc())
    assert sg.start_grade(root, s) == "ok"
    (root / "baselines/bedroom.state").unlink()
    assert sg.start_grade(root, s) == "missing"
    ck = root / "runs/checkpoints"
    ck.mkdir(parents=True)
    ship = ck / "ss_anne_2f.state"
    ship.write_bytes(b"s")
    statefp.write(ship, {"v": 1, "respawn": 3, "map": 96, "party": [[1, 5, 0, 30, 30]]})
    ship_seg = ss.Segment("x", "x", "ss_anne_2f", "x", "x", None)
    assert "behind Vermilion" in (sg.start_grade(root, ship_seg) or "")


def test_segment_par_two_map_grid_and_missing_leg():
    from pokeagent.legs.grid import from_ascii
    g1 = from_ascii(["...", "..."])                   # 3x2 open floor
    g2 = from_ascii(["....", "...."])
    grids = {1: g1, 2: g2}.get
    ee = [((0, 0), (2, 0)), ((0, 0), (3, 1))]
    par = sg.segment_par([1, 2], ee, grids)
    # leg1: (0,0)->(2,0) = 2 walks = 32 + FRAME_WALK leaving press 16; leg2: (0,0)->(3,1) = 4 walks = 64
    assert par == 32 + 16 + 64
    assert sg.segment_par([1, 2], [ee[0], None], grids) is None   # unknown leg -> None
    assert sg.segment_par([1, 9], ee, grids) is None              # unknown map -> None
    assert sg.segment_par([1, 2], ee, None) is None               # no grids -> None


def test_effective_shares_base_and_scaling():
    base = {"unsolved": 0.40, "frontier": 0.45, "polish": 0.15}
    assert sg.effective_shares([], base) == base                         # nothing graded: identical to today
    def mk(**kw):
        d = dict(key="k", solved=False, optimized=False, stale=False, broken=False, held=None,
                 rate=0.9, attempts=10, best=100, expected=200, par=None, health=0.5,
                 blackout_rate=None, stall_rate=None, loop_rate=None, start="ok",
                 provenance="organic", synthetic_only=False, last_ts=0.0, sha_before=None, sha_after=None)
        return sg.Grade(**{**d, **kw})
    grades = [mk(solved=True) for _ in range(5)]                         # 5 solved-not-optimized
    eff = sg.effective_shares(grades, base)
    assert eff["polish"] == min(sg.POLISH_MAX, 0.15 * (1 + 5 / sg.POLISH_RAMP))
    assert abs(sum(eff.values()) - 1.0) < 1e-9
    eff0 = sg.effective_shares([mk()], base)
    assert eff0["polish"] == sg.POLISH_MIN                               # nothing to polish: floor
    assert sg.explore_for_health(0.1) > sg.explore_for_health(0.9)       # sick frontier scouts more
    assert sg.frontier_health(None) == 0.5
