from pokeagent.human_hold import HumanHold


def test_hold():
    t = [0.0]
    h = HumanHold(3.0, clock=lambda: t[0])
    assert not h.active()
    h.touch()
    assert h.active()
    t[0] = 2.0
    h.touch()
    t[0] = 4.5
    assert h.active()  # second touch extended it
    t[0] = 5.1
    assert not h.active()
    h.touch()
    h.release()
    assert not h.active()
