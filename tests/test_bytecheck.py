"""bytecheck: synthetic reference only, no ROM."""
import json
import random
from pathlib import Path

import numpy as np
import pytest

from pokeagent import cli
from pokeagent.bytecheck import policy
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


def test_staged_without_index(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["bytecheck", "staged", "--index", "nope.npz"]) == 2
    assert "bytecheck build --ref" in capsys.readouterr().out
    assert cli.main(["bytecheck", "staged", "--index", "nope.npz", "--skip-if-no-index"]) == 0


def test_staged_scans_index_blob(idx, tmp_path, monkeypatch):
    import subprocess
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    Path("leak.bin").write_bytes(REF[:600])
    subprocess.run(["git", "add", "leak.bin"], check=True)
    ip = save_index(idx, tmp_path / "i.npz")
    assert cli.main(["bytecheck", "staged", "--index", str(ip)]) == 1
