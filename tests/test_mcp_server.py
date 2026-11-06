import asyncio

import pytest
from mcp.server.mcpserver import Image

from pokeagent import cli
from pokeagent.emu_thread import EmulatorThread
from pokeagent.emulator import Button, FakeEmulator
from pokeagent.mcp_server import _Tools, build_server

TOOL_NAMES = {
    "press", "wait", "state", "screenshot", "peek", "snapshot", "diff",
    "save_state", "load_state", "pause", "resume", "note", "explore",
    # live-agent intervention tools (pokeagent.intervene.mcp_tools)
    "agents_digest", "agent_show", "agent_hold", "agent_release", "agent_macro", "agent_nudge",
}


@pytest.fixture
def emuthread():
    made = []

    def factory():
        emu = FakeEmulator({0xD35E: 0x26, 0xD361: 4, 0xD362: 5})
        made.append(emu)
        return emu

    thread = EmulatorThread(factory, idle_fps=0)
    thread.start()
    yield thread, made[0]
    thread.stop()


def make_tools(thread, tmp_path):
    """The same callables build_server registers, on the same thread."""
    return _Tools(thread, runs_dir=tmp_path / "mcp", maps_path=tmp_path / "maps.json")


def test_state_returns_summary(emuthread, tmp_path):
    thread, _ = emuthread
    out = make_tools(thread, tmp_path).state()
    assert out["map_id"] == 0x26 and out["x"] == 5 and out["y"] == 4
    assert "map=0x26" in out["summary"]


def test_press_records_presses_and_returns_state(emuthread, tmp_path):
    thread, emu = emuthread
    out = make_tools(thread, tmp_path).press("RIGHT", repeat=2)
    assert emu.presses == [Button.RIGHT, Button.RIGHT]
    assert out["x"] == 5


def test_press_unknown_button_returns_error(emuthread, tmp_path):
    thread, _ = emuthread
    out = make_tools(thread, tmp_path).press("JUMP")
    assert "error" in out and "JUMP" in out["error"]


def test_wait_ticks_frames(emuthread, tmp_path):
    thread, emu = emuthread
    make_tools(thread, tmp_path).wait(30)
    assert emu.frames == 30


def test_peek_hex_formatting(emuthread, tmp_path):
    thread, _ = emuthread
    out = make_tools(thread, tmp_path).peek(0xD362)
    assert out == {"addr": "0xD362", "hex": "05", "bytes": [5]}


def test_peek_refuses_length_over_4096(emuthread, tmp_path):
    thread, _ = emuthread
    assert "error" in make_tools(thread, tmp_path).peek(0xC000, length=4097)


def test_snapshot_and_diff_report_scripted_change(emuthread, tmp_path):
    thread, emu = emuthread
    tools = make_tools(thread, tmp_path)
    assert tools.snapshot("a")["bytes"] == 0x2000
    emu.set(0xC010, 0x99)
    emu.set(0xD362, 0x07)  # a RAM_MAP-named address
    tools.snapshot("b")
    by_addr = {e["addr"]: e for e in tools.diff("a", "b")}
    assert by_addr["0xC010"] == {"addr": "0xC010", "old": 0, "new": 0x99}
    assert by_addr["0xD362"]["name"] == "player_x"


def test_diff_unknown_snapshot_errors(emuthread, tmp_path):
    thread, _ = emuthread
    assert "error" in make_tools(thread, tmp_path).diff("a", "b")


def test_save_and_load_state_round_trip(emuthread, tmp_path):
    thread, emu = emuthread
    tools = make_tools(thread, tmp_path)
    out = tools.save_state("checkpoint!")
    path = tmp_path / "mcp" / "checkpoint.state"  # name sanitised to [A-Za-z0-9_-]
    assert out["path"] == str(path) and path.is_file()
    emu.set(0xD362, 9)
    assert tools.load_state("checkpoint")["path"] == str(path)
    assert emu.read(0xD362) == 5


def test_load_state_by_path_under_cwd(emuthread, tmp_path, monkeypatch):
    thread, emu = emuthread
    src = FakeEmulator({0xD362: 0x42})
    state_file = tmp_path / "elsewhere.state"
    src.save_state(state_file)
    monkeypatch.chdir(tmp_path)
    tools = make_tools(thread, tmp_path)
    assert tools.load_state(str(state_file))["path"] == str(state_file)
    assert emu.read(0xD362) == 0x42


def test_load_state_missing_returns_error(emuthread, tmp_path):
    thread, _ = emuthread
    assert "error" in make_tools(thread, tmp_path).load_state("nope")


def test_pause_and_resume_toggle_thread(emuthread, tmp_path):
    thread, _ = emuthread
    tools = make_tools(thread, tmp_path)
    assert tools.pause() == {"paused": True} and thread.paused
    assert tools.resume() == {"paused": False} and not thread.paused


def test_note_appends_and_returns_tail(emuthread, tmp_path):
    thread, _ = emuthread
    tools = make_tools(thread, tmp_path)
    tools.note("first")
    out = tools.note("second")
    assert out["lines"][-2:] == ["first", "second"]
    assert (tmp_path / "mcp" / "notes.txt").is_file()


def test_screenshot_returns_png_image(emuthread, tmp_path):
    thread, _ = emuthread
    img = make_tools(thread, tmp_path).screenshot()
    assert isinstance(img, Image)
    assert img.data[:4] == b"\x89PNG"


def test_explore_runs_steps_and_returns_memory(emuthread, tmp_path):
    thread, emu = emuthread
    tools = make_tools(thread, tmp_path)
    out = tools.explore(3)
    assert out["ran"] == 3
    assert len(emu.presses) == 3
    assert "visited" in out["memory"]
    assert (tmp_path / "maps.json").is_file()


def test_server_registers_all_tools(emuthread, tmp_path):
    thread, _ = emuthread
    server = build_server(
        thread, runs_dir=tmp_path / "mcp", maps_path=tmp_path / "maps.json"
    )
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == TOOL_NAMES


def test_state_resource_is_registered(emuthread, tmp_path):
    thread, _ = emuthread
    server = build_server(
        thread, runs_dir=tmp_path / "mcp", maps_path=tmp_path / "maps.json"
    )
    uris = {str(r.uri) for r in asyncio.run(server.list_resources())}
    assert "pokeagent://state" in uris


def test_call_tool_through_sdk_dispatch(emuthread, tmp_path):
    thread, _ = emuthread
    server = build_server(
        thread, runs_dir=tmp_path / "mcp", maps_path=tmp_path / "maps.json"
    )
    result = asyncio.run(server.call_tool("state", {}))
    assert not result.is_error
    assert result.structured_content["map_id"] == 0x26


def test_mcp_subcommand_parses(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["mcp", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--rom", "--state", "--headless", "--idle-fps"):
        assert flag in out
