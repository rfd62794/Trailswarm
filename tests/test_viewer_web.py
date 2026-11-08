"""The web page declares its own frame wants: an agent the window never showed still gets a
frame on the poll after its request (the want lives ``WEB_WANT_S`` seconds, then expires)."""
import threading
import urllib.error
import urllib.request

import pytest

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import FakeSource
from pokeagent.viewer.web import WEB_WANT_S, make_server


class Counting(FakeSource):
    def __init__(self, aid):
        super().__init__(aid, [AgentSnapshot(agent_id=aid)] * 8, [(b"\x00" * 12, 2, 2)])
        self.frames = 0

    def frame(self):
        self.frames += 1
        return (b"\x00" * 12, 2, 2)


def _serve(model):
    httpd = make_server(model, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_frame_png_declares_want_and_serves_after_next_poll():
    t = [0.0]
    model = ViewerModel(clock=lambda: t[0])
    src = Counting("off")                                # off-screen: no window declared a want
    model.poll([src]); model.drain()
    assert src.frames == 0
    httpd, base = _serve(model)
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:     # first hit: want declared, not yet polled
            urllib.request.urlopen(base + "/frame.png?id=off", timeout=5)
        assert ei.value.code == 404
        t[0] += 0.1
        model.poll([src]); model.drain()
        assert src.frames == 1                                # the web want drove one frame read
        png = urllib.request.urlopen(base + "/frame.png?id=off", timeout=5).read()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        t[0] += WEB_WANT_S + 1.0
        model.poll([src]); model.drain()
        assert src.frames == 1                                # the want expired: no more reads
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_data_declares_wants_for_every_listed_agent():
    t = [0.0]
    model = ViewerModel(clock=lambda: t[0])
    srcs = [Counting("a"), Counting("b")]
    model.poll(srcs); model.drain()
    assert all(s.frames == 0 for s in srcs)
    httpd, base = _serve(model)
    try:
        urllib.request.urlopen(base + "/data", timeout=5).read()
        t[0] += 0.1
        model.poll(srcs); model.drain()
        assert all(s.frames == 1 for s in srcs)               # every card on the page wants frames
    finally:
        httpd.shutdown()
        httpd.server_close()
