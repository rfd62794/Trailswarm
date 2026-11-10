"""The one selection: featured, auto-vs-user stickiness, gameplay_agent, camera_target (pure)."""
from pokeagent.mapview.live import LivePos
from pokeagent.viewer import selection as s


def pos(agent, at, area="a", x=1.0, y=2.0):
    return LivePos(agent, "", area, x, y, None, None, at)


def test_featured_freshest_live_registry_agent():
    live = {"b": pos("b", 5.0), "a": pos("a", 9.0), "x": pos("x", 99.0)}
    assert s.featured(live, ["a", "b"]) == "a"        # x is not in the registry: ignored for featuring
    assert s.featured({}, ["a", "b"]) == "a"          # no live file: first registry id
    assert s.featured({"x": pos("x", 1.0)}, ["a", "b"]) == "a"
    assert s.featured({"a": pos("a", 1.0)}, []) is None
    assert s.featured({}, []) is None


def test_selection_auto_follows_featured_and_user_pick_sticks():
    sel = s.Selection()
    live = {"a": pos("a", 1.0)}
    assert sel.update(live, ["a", "b"]) == "a" and sel.source == "auto" and sel.is_live
    sel.select("g-1", "ghost")
    assert sel.update(live, ["a", "b"]) == "g-1" and not sel.is_live and sel.source == "user"
    sel.auto()
    assert sel.update(live, ["a", "b"]) == "a" and sel.source == "auto"


def test_selected_registry_agent_vanishing_releases_to_auto():
    sel = s.Selection()
    sel.select("b", "live")
    assert sel.update({}, ["a", "b"]) == "b"                     # still registered: sticky
    assert sel.update({}, ["a"]) == "a" and sel.source == "auto"  # gone: back to auto


def test_ghost_pick_survives_registry_churn():
    sel = s.Selection()
    sel.select("g-1", "ghost")
    assert sel.update({}, []) == "g-1" and sel.source == "user"   # a ghost pick is not released


def test_gameplay_agent():
    sel = s.Selection()
    sel.select("a", "live")
    assert s.gameplay_agent(sel, ["a"], "a") == ("a", "")
    sel.select("g-1", "ghost")
    assert s.gameplay_agent(sel, ["a"], "a") == ("a", "g-1: recorded run, no live frames - showing a")
    assert s.gameplay_agent(sel, [], None) == (None, "no live agent")


def test_camera_target():
    sel = s.Selection()
    assert s.camera_target(sel, {}, lambda a: None) is None                     # nothing selected
    sel.select("a", "live")
    pts = {"a": (10.0, 20.0)}
    assert s.camera_target(sel, pts, lambda a: None) == (10.0, 20.0)
    sel.select("g-1", "ghost")
    assert s.camera_target(sel, pts, lambda a: (5.0, 6.0) if a == "g-1" else None) == (5.0, 6.0)
    assert s.camera_target(sel, pts, lambda a: None) is None
    sel.select("b", "live")
    assert s.camera_target(sel, pts, lambda a: None) is None                    # live, no position
