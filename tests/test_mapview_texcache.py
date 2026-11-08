from pokeagent.mapview.texcache import TexCache


def test_retire_keeps_old_drawable_until_swept_and_deletes_each_once():
    gone = []
    c = TexCache(gone.append, 3)
    c.put(0, 1, 1, "t1")
    c.put(0, 2, 1, "t2")
    c.retire()
    assert c.get(0, 1, 1) is None and c.fallback(0, 1, 1) == "t1" and gone == []
    c.put(0, 1, 1, "n1")
    c.sweep()
    assert sorted(gone) == ["t1", "t2"] and c.fallback(0, 1, 1) is None
    c.retire()
    c.retire()                      # second rebuild supersedes: n1 deleted exactly once
    assert gone.count("n1") == 1 and c.stale == {}
