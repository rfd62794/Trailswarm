import json

from pokeagent.decision import Decision, VALID_BUTTONS, parse_reply


def test_plain_json_all_fields():
    d = parse_reply('{"thinking": "go up", "button": "A", "note": "door north"}')
    assert d.button == "A"
    assert d.thinking == "go up"
    assert d.note == "door north"
    assert d.error == ""


def test_fenced_json():
    d = parse_reply('```json\n{"thinking": "t", "button": "B"}\n```')
    assert d.button == "B"
    assert d.thinking == "t"


def test_json_inside_prose():
    d = parse_reply('Sure! I would press {"thinking": "stairs", "button": "DOWN"} now.')
    assert d.button == "DOWN"
    assert d.thinking == "stairs"


def test_lowercase_button():
    d = parse_reply('{"button": "up"}')
    assert d.button == "UP"
    assert d.error == ""


def test_unknown_button_keeps_thinking():
    d = parse_reply('{"thinking": "hmm", "button": "JUMP"}')
    assert d.button == "NONE"
    assert "unknown button" in d.error
    assert d.thinking == "hmm"


def test_missing_button():
    d = parse_reply('{"thinking": "no idea"}')
    assert d.button == "NONE"
    assert "missing button" in d.error
    assert d.thinking == "no idea"


def test_empty_string():
    d = parse_reply("")
    assert d.button == "NONE"
    assert d.error == "no json object"


def test_prose_without_braces():
    d = parse_reply("just press A please")
    assert d.button == "NONE"
    assert d.error == "no json object"


def test_thinking_truncated_to_1000():
    d = parse_reply(json.dumps({"thinking": "x" * 2000, "button": "A"}))
    assert d.button == "A"
    assert len(d.thinking) == 1000


def test_note_truncated_to_500():
    d = parse_reply(json.dumps({"note": "y" * 900, "button": "A"}))
    assert len(d.note) == 500


def test_raw_kept_on_failure():
    text = "z" * 600 + "{bad"
    d = parse_reply(text)
    assert d.button == "NONE"
    assert d.error == "unbalanced braces"
    assert d.raw == text[:500]


def test_bad_json_object_falls_through_to_valid_one():
    d = parse_reply('note: {not json} then {"button": "START"}')
    assert d.button == "START"


def test_braces_inside_strings_do_not_unbalance():
    d = parse_reply('{"thinking": "brace } here", "button": "LEFT"}')
    assert d.button == "LEFT"
    assert d.thinking == "brace } here"


def test_decision_uppercases_button():
    assert Decision("a").button == "A"


def test_decision_invalid_button_coerced_to_none():
    d = Decision("warp")
    assert d.button == "NONE"
    assert d.error


def test_valid_buttons_contents():
    assert VALID_BUTTONS == (
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "A",
        "B",
        "START",
        "SELECT",
        "NONE",
    )
