"""Panel view functions: pure snapshot -> styled lines/pixels, no UI toolkit."""
import pytest

from pokeagent.snapshot import AgentSnapshot, Event, Goal, PartyMon, Screen, Sees, Segment, Thinking
from pokeagent.viewer.panels import DIM, DRIVER_COLORS, TEXT, registry
from pokeagent.viewer.panels import focus as focus_panel
from pokeagent.viewer.panels import progress as progress_panel
from pokeagent.viewer.panels import render, sees as sees_panel
from pokeagent.viewer.panels import thinking as thinking_panel


def rich_snapshot() -> AgentSnapshot:
    return AgentSnapshot(
        agent_id="run-1", kind="explorer", state="running", step=57,
        segment=Segment(id="S3", name="first_pokemon", steps=43, record=74),
        goals=[Goal(id="potion", name="potion", status="done", steps=14),
               Goal(id="left_house", name="left_house", status="done", steps=38),
               Goal(id="first_pokemon", name="first_pokemon", status="current"),
               Goal(id="won_battle", name="won_battle", status="ahead")],
        thinking=Thinking(want="first_pokemon", plan="goto -> lab door", driver="explorer",
                          rule="plan_goal/route", button="UP", result="moved", brain="brain: OVERWORLD -> A(0.07)"),
        recent=[Event(step=55, driver="explorer", text="goto step 3"),
                Event(step=56, driver="human", text="you pressed A")],
        sees=Sees(rows=["~~~~####~~", "~~~#..#~~", "..@...~~?", "  @ the player  # wall"], mode="overworld"),
        screen=Screen(box_text="PC: WITHDRAW ITEM", in_battle=False,
                      party=[PartyMon(species="CHARMANDER", level=5, hp=12, max_hp=16)],
                      money=300, bag_summary="POTION x1"),
        human_hold=True,
    )


def texts(lines) -> str:
    return "\n".join("".join(t for t, _ in line) for line in lines)


def colors(line):
    return [c for _, c in line]


def test_frame_rgba_nearest():
    rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])  # 2x2: R G / B Y
    out = render.frame_rgba(rgb, 2, 2, 4, 4)
    assert len(out) == 4 * 4 * 4
    assert list(out[:4]) == [1.0, 0.0, 0.0, 1.0]          # top-left = red
    assert list(out[(1 * 4 + 1) * 4:(1 * 4 + 1) * 4 + 4]) == [1.0, 0.0, 0.0, 1.0]  # (1,1) still src(0,0) = red
    assert list(out[(3 * 4 + 3) * 4:(3 * 4 + 3) * 4 + 4]) == [1.0, 1.0, 0.0, 1.0]  # (3,3) = yellow
    assert list(out[(3 * 4 + 0) * 4:(3 * 4 + 0) * 4 + 4]) == [0.0, 0.0, 1.0, 1.0]  # bottom-left = blue


def test_frame_png():
    png = render.frame_png(bytes([0, 0, 0] * 4), 2, 2, scale=2)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_sees_glyphs_legend_and_battle():
    snap = rich_snapshot()
    lines = sees_panel.sees_lines(snap)
    glyph_row = lines[0]
    assert "".join(t for t, _ in glyph_row) == "~~~~####~~"
    assert set(colors(glyph_row)) != {DIM}         # per-glyph colours, not one flat dim
    assert colors(glyph_row)[0] == sees_panel._CHAR_COLOR["~"]
    legend_row = lines[3]
    assert all(c == DIM for c in colors(legend_row))  # legend text is dim

    battle = AgentSnapshot(agent_id="b", sees=Sees(rows=["BATTLE kind=0x02", "you L5 HP 10/16"], mode="battle"))
    blines = sees_panel.sees_lines(battle)
    assert all(c == TEXT for line in blines for _, c in line)

    empty = AgentSnapshot(agent_id="e")
    assert sees_panel.sees_lines(empty) == [[("(no vision)", DIM)]]


def test_thinking_lines_and_hold_countdown():
    lines = thinking_panel.thinking_lines(rich_snapshot(), hold_s=2.1)
    text = texts(lines)
    assert "YOU HAVE IT 2.1s" in text
    assert "want  first_pokemon" in text
    assert "plan   goto -> lab door" in text
    assert "brain: OVERWORLD -> A(0.07)" in text
    driver_line = next(line for line in lines if any("explorer" in t for t, _ in line))
    assert driver_line[0] == ("explorer", DRIVER_COLORS["explorer"])
    assert "UP -> moved" in texts([line for line in lines if "UP" in "".join(t for t, _ in line)])

    no_hold = thinking_panel.thinking_lines(AgentSnapshot(agent_id="x", human_hold=True))
    assert "YOU HAVE IT" in texts(no_hold) and "2.1" not in texts(no_hold)

    blocker = AgentSnapshot(agent_id="x", thinking=Thinking(want="w", blocker="stuck on ledge", driver="rl"))
    btext = texts(thinking_panel.thinking_lines(blocker))
    assert "blocker  stuck on ledge" in btext and "plan" not in btext
    rline = next(line for line in thinking_panel.thinking_lines(blocker) if any("rl" == t.strip() for t, _ in line))
    assert rline[0][1] == DRIVER_COLORS["rl"]


def test_progress_strip_and_info():
    lines = progress_panel.progress_lines(rich_snapshot())
    strip, info = lines[0], lines[1]
    assert "".join(t for t, _ in strip) == "S1 S2 S3 S4 "
    assert colors(strip) == ["#5fa85f", "#5fa85f", "#e0b050", "#3f444e"]
    assert "first_pokemon: 43 steps (best 74)" in texts([info]) and "step 57" in texts([info])

    rl = AgentSnapshot(agent_id="r", segment=Segment(id="a1c", record=123), step=9)
    rlines = progress_panel.progress_lines(rl)
    assert "a1c: 0 steps (best 123)" in texts(rlines) and "step 9" in texts(rlines)
    assert len(rlines) == 1  # no goals -> no strip, no sparkline


def test_focus_extras():
    lines = focus_panel.focus_lines(rich_snapshot())
    text = texts(lines)
    assert "recent" in text and "goto step 3" in text and "you pressed A" in text
    assert "CHARMANDER L5  12/16" in text and "money 300" in text and "POTION x1" in text
    assert "PC: WITHDRAW ITEM" not in text  # box_text is not a focus extra
    assert "v potion (14)" in text and "> first_pokemon" in text and "- won_battle" in text
    ev_line = next(line for line in lines if "you pressed A" in "".join(t for t, _ in line))
    assert ("human", DRIVER_COLORS["human"]) in ev_line


def test_panels_on_minimal_and_stopped_snapshots():
    """Missing fields and stopped/lost agents must not crash any panel."""
    for snap in (AgentSnapshot(agent_id="min"),
                 AgentSnapshot(agent_id="stop", state="stopped", stop_reason="step cap"),
                 AgentSnapshot(agent_id="lost", state="done", stop_reason="goal:won_battle")):
        for name in registry.PANELS:
            assert registry.lines_for(name, snap) is not None
        for fn in (sees_panel.sees_lines, thinking_panel.thinking_lines,
                   progress_panel.progress_lines, focus_panel.focus_lines):
            assert isinstance(fn(snap), list)


def test_registry_order_and_dispatch():
    assert registry.PANELS == ("render", "sees", "thinking", "progress")
    assert registry.FOCUS_PANELS == registry.PANELS + ("focus",)
    assert registry.lines_for("render", rich_snapshot()) == []
    assert registry.lines_for("nope", rich_snapshot()) == []
    assert registry.lines_for("sees", rich_snapshot()) == sees_panel.sees_lines(rich_snapshot())


def test_sees_text_scale_is_fixed_across_line_sets():
    from pokeagent.viewer.panels import plain
    from pokeagent.viewer.panels.textimg import SEES_GRID, fit_lines, lines_texture
    over = [plain("@N.T......", "#ffffff")] * 9
    battle = [plain("A very long battle line that overflows", "#ffffff")] * 3
    a = lines_texture(over, 200, 180, grid=SEES_GRID)
    b = lines_texture(battle, 200, 180, grid=SEES_GRID)
    assert a[1:] == b[1:] == (400, 360)
    cut = fit_lines(battle, SEES_GRID[1], SEES_GRID[0])
    assert len(cut[0][0][0]) == SEES_GRID[0] and cut[0][0][0].endswith("\u2026")
    # row pitch is constant: the same line lands at the same pixel rows with 2 or 9 lines
    one = [plain("X", "#ffffff")]
    x1 = lines_texture(one, 200, 180, grid=SEES_GRID)[0]
    x2 = lines_texture(one + [plain("Y", "#ffffff")] * 8, 200, 180, grid=SEES_GRID)[0]
    top = 40 * 800  # first 40 pixel rows (row 0 band) identical
    assert (x1[:top] == x2[:top]).all()
    assert lines_texture(over[:2], 200, 100)[1:] == lines_texture(over, 200, 100)[1:]
