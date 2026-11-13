"""bytecheck: synthetic reference only, no ROM."""
import json
import random
from pathlib import Path

import numpy as np
import pytest

from pokeagent import cli
from pokeagent.bytecheck import cli as bc_cli, policy
from pokeagent.bytecheck.fingerprint import build_index, load_index, save_index
from pokeagent.bytecheck.scan import scan_bytes
from pokeagent.bytecheck.windows import WINDOW


def rnd(n, seed):
    return random.Random(seed).randbytes(n)


REF = rnd(100_000, 1)


@pytest.fixture(scope="module")
def idx():
    return build_index(REF)


def test_slice_is_leak(idx):
    res = scan_bytes(rnd(500, 2) + REF[5000:5300] + rnd(500, 3), idx)
    assert res.longest_run == 300 and res.top_runs[0]["offset"] == 500
    assert res.top_runs[0]["ref_offset"] == 5000
    assert policy.verdict(res, "media") == policy.LEAK


def test_unrelated_clean(idx):
    res = scan_bytes(rnd(50_000, 4), idx)
    assert res.matched_windows == 0
    assert policy.verdict(res, "commit") == policy.CLEAN


def test_fill_runs_clean():
    ref = bytes(2000) + rnd(1000, 5) + b"\xff" * 2000
    i = build_index(ref)
    for target in (bytes(5000), b"\xff" * 5000, bytes(100) + b"\xff" * 100):
        assert scan_bytes(target, i).matched_windows == 0
        assert policy.verdict(scan_bytes(target, i), "commit") == policy.CLEAN


def test_state_tolerates_small_table(idx):
    res = scan_bytes(rnd(2000, 6) + REF[1000:1600] + rnd(2000, 7), idx)   # 600 B table copy
    assert policy.verdict(res, "state") == policy.CLEAN
    assert policy.verdict(res, "media") == policy.LEAK
    big = scan_bytes(REF[:20000], idx)
    assert policy.verdict(big, "state") == policy.LEAK


def test_index_holds_no_reference_bytes(idx, tmp_path):
    path = save_index(idx, tmp_path / "i.npz")
    blob = path.read_bytes()
    raw = (tmp_path / "raw.bin")
    save_index(idx, raw)
    for p in (path, raw):
        blob = p.read_bytes()
        assert not any(REF[o:o + WINDOW] in blob for o in range(0, len(REF) - WINDOW, 7))
    loaded = load_index(path)
    assert np.array_equal(loaded.hashes, idx.hashes) and loaded.ref_size == len(REF)


def test_cli_exit_codes(idx, tmp_path, capsys):
    ip = save_index(idx, tmp_path / "i.npz")
    leak, ok = tmp_path / "leak.png.bin", tmp_path / "ok.bin"
    leak.write_bytes(REF[:400])
    ok.write_bytes(rnd(400, 9))
    base = ["bytecheck", "scan", "--index", str(ip)]
    assert cli.main(base + [str(ok)]) == 0
    assert cli.main(base + [str(leak), "--profile", "media"]) == 1
    capsys.readouterr()
    assert cli.main(base + [str(leak), "--profile", "media", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "LEAK"
    assert cli.main(["bytecheck", "scan", "--index", str(tmp_path / "none"), str(ok)]) == 2


def test_cli_build_roundtrip(tmp_path, capsys):
    rom = tmp_path / "fake.gb"
    rom.write_bytes(REF[:5000])
    out = tmp_path / "idx.npz"
    assert cli.main(["bytecheck", "build", "--ref", str(rom), "--index", str(out)]) == 1  # sha mismatch
    assert cli.main(["bytecheck", "build", "--ref", str(rom), "--index", str(out),
                     "--allow-mismatch"]) == 0
    assert load_index(out).ref_size == 5000


def test_png_pixels_scanned(idx, tmp_path):
    from PIL import Image
    from pokeagent.bytecheck.scan import scan_file
    im = Image.frombytes("RGBA", (64, 4), REF[:1024])
    p = tmp_path / "a.png"
    im.save(p)
    assert scan_file(p, idx).longest_run >= 1000


def _repo(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    return lambda *a: subprocess.run(["git", *a], check=True)


def test_staged_without_index(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    assert cli.main(["bytecheck", "staged", "--index", "nope.npz"]) == 2
    assert "bytecheck build --ref" in capsys.readouterr().out
    assert cli.main(["bytecheck", "staged", "--index", "nope.npz", "--skip-if-no-index"]) == 0


def test_padded_rom_slice_keeps_one_long_run():
    pad = b"\xff" * 40                                   # 40 x 0xFF drops every window with > 24 fill bytes
    chunks = [rnd(300, 20), pad, rnd(300, 21), pad, rnd(300, 22), pad, rnd(300, 23), pad, rnd(300, 24)]
    ref = rnd(500, 25) + b"".join(chunks) + rnd(500, 26)
    i = build_index(ref)
    piece = ref[500:500 + 2048]
    assert len(piece) == 2048
    res = scan_bytes(rnd(700, 27) + piece + rnd(700, 28), i)
    assert res.longest_run >= 1536, res.longest_run
    assert res.top_runs[0]["offset"] == 700 and res.top_runs[0]["ref_offset"] == 500



def test_gap_with_different_ref_delta_is_not_bridged():
    a, b = rnd(400, 30), rnd(400, 31)
    ref = a + rnd(40, 32) + b
    i = build_index(ref)
    res = scan_bytes(a + b, i)                           # b is not where it was in the reference: two runs, not one
    assert res.longest_run == 400


def test_staged_scans_index_blob(idx, tmp_path, monkeypatch):
    git = _repo(tmp_path, monkeypatch)
    Path("leak.bin").write_bytes(REF[:600])
    git("add", "leak.bin")
    Path("leak.bin").write_bytes(rnd(600, 40))            # the working file is clean now; the index still holds ROM bytes
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 1
    git("add", "leak.bin")                                # restage the clean bytes: now CLEAN
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 0


def test_staged_from_subdirectory_resolves_against_toplevel(idx, tmp_path, monkeypatch):
    git = _repo(tmp_path, monkeypatch)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "leak.bin").write_bytes(REF[:600])
    git("add", "sub/leak.bin")
    ip = save_index(idx, tmp_path / "i.npz")
    monkeypatch.chdir(tmp_path / "sub")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 1


def test_staged_unreadable_path_fails_loudly(idx, tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path, monkeypatch)
    Path("a.txt").write_text("hello")
    git("add", "a.txt")
    ip = save_index(idx, tmp_path / "i.npz")
    monkeypatch.setattr(bc_cli, "_staged_blob", lambda top, p: None)
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) != 0
    assert "NOT scanned" in capsys.readouterr().out


def test_staged_outside_a_repo_fails(idx, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 2


@pytest.mark.parametrize("name", ["a.gb", "b.GBC", "c.gba", "d.sgb"])
def test_staged_rom_extension_is_blocked_even_if_clean_or_no_index(idx, tmp_path, monkeypatch, capsys, name):
    git = _repo(tmp_path, monkeypatch)
    Path(name).write_bytes(rnd(400, 50))                  # matches nothing in the index
    git("add", name)
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 1
    assert "BLOCKED" in capsys.readouterr().out
    assert cli.main(["bytecheck", "staged", "--index", "nope.npz", "--skip-if-no-index"]) == 1


def test_staged_sav_is_suspect_with_warning(idx, tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path, monkeypatch)
    Path("game.sav").write_bytes(rnd(400, 51))
    git("add", "game.sav")
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 0
    cap = capsys.readouterr()
    assert "SUSPECT" in cap.out and "game.sav" in cap.out and "warning" in cap.err and "warning" not in cap.out


def test_staged_json_with_sav_parses(idx, tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path, monkeypatch)
    Path("game.sav").write_bytes(rnd(400, 52))
    git("add", "game.sav")
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)          # stdout is pure JSON
    assert data["verdict"] == "SUSPECT" and any("game.sav" in w for w in data["warnings"])


def test_staged_submodule_is_skipped(idx, tmp_path, monkeypatch, capsys):
    import subprocess
    sub = tmp_path / "subsrc"
    sub.mkdir()
    env = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "protocol.file.allow=always"]
    subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
    (sub / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=sub, check=True)
    subprocess.run(["git", *env, "commit", "-qm", "i"], cwd=sub, check=True)
    main = tmp_path / "main"
    main.mkdir()
    monkeypatch.chdir(main)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", *env, "submodule", "add", "-q", str(sub), "vendor"], check=True)
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 0
    assert "skipped (submodule)" in capsys.readouterr().out
    assert cli.main(["bytecheck", "staged", "--index", str(ip), "--json"]) == 0
    assert {"path": "vendor", "reason": "submodule"} in json.loads(capsys.readouterr().out)["skipped"]
