import io
import json

from pokeagent.agent import Agent
from pokeagent.backend import BackendError, StubBackend
from pokeagent.emulator import Button, FakeEmulator
from pokeagent.runlog import RunLog


def _make(tmp_path, backend, **agent_kw):
    emu = agent_kw.pop("emu", FakeEmulator())
    log = RunLog(tmp_path / "runs")
    out = io.StringIO()
    agent = Agent(emu, backend, log, out=out, **agent_kw)
    return agent, emu, log, out


def test_five_steps_records_five_presses(tmp_path):
    backend = StubBackend(default='{"thinking": "go", "button": "A"}')
    agent, emu, log, _ = _make(tmp_path, backend, max_steps=5)
    result = agent.run()
    assert result.steps == 5
    assert result.stop_reason == "max_steps"
    assert result.failures == 0
    assert emu.presses == [Button.A] * 5
    assert emu.closed
    lines = log.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    entry = json.loads(lines[0])
    for key in ("step", "state", "button", "thinking", "note", "error", "backend_ms"):
        assert key in entry
    assert (log.run_dir / "summary.json").is_file()


def test_three_unparseable_replies_stop_with_backend_failures(tmp_path):
    backend = StubBackend(default="not json at all")
    agent, emu, log, _ = _make(tmp_path, backend, max_steps=10)
    result = agent.run()
    assert result.steps == 3
    assert result.stop_reason == "backend_failures"
    assert result.failures == 3
    assert emu.presses == []  # every failed step coerces to NONE
    assert emu.closed


def test_clean_step_resets_consecutive_failure_counter(tmp_path):
    good = '{"button": "A"}'
    backend = StubBackend(replies=["bad", good, "bad", "bad"], default=good)
    agent, emu, log, _ = _make(tmp_path, backend, max_steps=6)
    result = agent.run()
    # failures at steps 1, 3, 4 never reach 3 in a row because step 2 reset it
    assert result.steps == 6
    assert result.stop_reason == "max_steps"
    assert result.failures == 3


def test_backend_error_counts_as_failure(tmp_path):
    class FailingBackend:
        name = "failing"

        def choose(self, prompt):
            raise BackendError("timeout after 120s")

    agent, emu, log, _ = _make(tmp_path, FailingBackend(), max_steps=10)
    result = agent.run()
    assert result.steps == 3
    assert result.stop_reason == "backend_failures"
    entry = json.loads(log.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["error"] == "timeout after 120s"


def test_snapshots_written_at_snapshot_every_and_at_end(tmp_path):
    backend = StubBackend(default='{"button": "B"}')
    agent, emu, log, _ = _make(tmp_path, backend, max_steps=5, snapshot_every=2)
    agent.run()
    assert (log.run_dir / "state_0002.state").is_file()
    assert (log.run_dir / "state_0004.state").is_file()
    assert (log.run_dir / "state_0005.state").is_file()  # final snapshot
    assert not (log.run_dir / "state_0001.state").exists()


def test_note_appended_to_notes_and_fed_back_next_step(tmp_path):
    backend = StubBackend(default='{"button": "A", "note": "saw a door"}')
    agent, emu, log, _ = _make(tmp_path, backend, max_steps=2)
    agent.run()
    assert "saw a door" in log.notes()
    assert "saw a door" in backend.prompts[1]


def test_console_block_shape_for_fake_run(tmp_path):
    backend = StubBackend(default='{"thinking": "go", "button": "A"}')
    agent, emu, log, out = _make(tmp_path, backend, max_steps=1)
    agent.run()
    text = out.getvalue()
    assert "--- step 1/1  map=0x00 pos=(0,0) party=0 badges=0 battle=no money=0" in text
    assert "thinking: go" in text
    assert "button:   A\n" in text


def test_keyboard_interrupt_stops_cleanly(tmp_path):
    class InterruptBackend:
        name = "interrupt"

        def choose(self, prompt):
            raise KeyboardInterrupt

    agent, emu, log, _ = _make(tmp_path, InterruptBackend(), max_steps=10)
    result = agent.run()
    assert result.stop_reason == "interrupted"
    assert result.steps == 0
    assert emu.closed
    assert (log.run_dir / "summary.json").is_file()
