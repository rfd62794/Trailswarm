from pokeagent.prompt import build_prompt
from pokeagent.ram import GameState


def _state():
    return GameState(
        map_id=0x26, x=3, y=6, party_count=1, badges=0,
        badge_count=0, in_battle=False, money=3000,
    )


def test_prompt_contains_goal_summary_notes_recent_and_contract():
    recent = [
        {"step": 1, "button": "A", "thinking": "press a"},
        {"step": 2, "button": "DOWN", "thinking": "go down"},
    ]
    p = build_prompt(_state(), recent, "remember the stairs", step=3, max_steps=50)
    assert "Pokemon Red" in p
    assert "Explore, talk to people, progress the story." in p
    assert _state().summary() in p
    assert "step 1: pressed A (press a)" in p
    assert "step 2: pressed DOWN (go down)" in p
    assert "## Your notes" in p
    assert "remember the stairs" in p
    assert '"thinking"' in p
    assert '"button"' in p
    assert "UP|DOWN|LEFT|RIGHT|A|B|START|SELECT|NONE" in p
    assert "No other text" in p


def test_prompt_recent_capped_at_ten():
    recent = [{"step": i, "button": "A", "thinking": "t"} for i in range(1, 15)]
    p = build_prompt(_state(), recent, "", step=15, max_steps=50)
    assert "step 4: pressed A" not in p
    assert "step 5: pressed A" in p
    assert "step 14: pressed A" in p


def test_prompt_empty_recent_and_notes_have_placeholders():
    p = build_prompt(_state(), [], "", step=1, max_steps=50)
    assert "(none yet)" in p
    assert "(empty)" in p


def test_prompt_recent_line_omits_empty_thinking_parens():
    recent = [{"step": 1, "button": "B", "thinking": ""}]
    p = build_prompt(_state(), recent, "", step=2, max_steps=50)
    assert "step 1: pressed B" in p
    assert "pressed B ()" not in p
