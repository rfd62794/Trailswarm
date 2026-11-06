"""Read-only web view of the same ViewerModel: ``/`` page, ``/data`` JSON, ``/frame.png``.

Binds 127.0.0.1 only; GET-only (no POST anywhere). Started by ``pokeagent view --web``.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.panels import render as pres

_PAGE = """<!doctype html><meta charset=utf-8><title>pokeagent view</title>
<style>body{background:#1e1f24;color:#d8d8d8;font:13px Consolas,monospace;margin:12px}
.card{display:inline-block;vertical-align:top;border:1px solid #333;border-radius:4px;margin:4px;padding:6px;width:340px}
img{image-rendering:pixelated;width:170px}pre{white-space:pre-wrap;margin:4px 0}.dim{color:#8a8f98}</style>
<div id=app>loading…</div>
<script>
async function tick(){
  const d = await (await fetch('/data')).json();
  document.getElementById('app').innerHTML = d.agents.map(a=>`
    <div class=card><b style="color:${a.color}">${a.id}</b> <span class=dim>${a.kind} ${a.state} step ${a.step} ${a.staleness}</span><br>
    ${a.frame?`<img src="/frame.png?id=${encodeURIComponent(a.id)}">`:''}
    <pre>${a.sees.map(esc).join('\n')}</pre><pre class=dim>${a.text.map(esc).join('\n')}</pre></div>`).join('') || 'no agents';
}
const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
setInterval(tick, 500); tick();
</script>"""


def _agent_json(model: ViewerModel, aid: str) -> dict:
    snap = model.snapshot(aid)
    frame = model.frame(aid)
    out = {"id": aid, "staleness": model.staleness(aid), "frame": frame is not None,
           "sees": [], "text": [], "color": "#8a8f98"}
    if snap is None:
        return out
    out.update(kind=snap.kind, state=snap.state, step=snap.step, agent_id=snap.agent_id)
    out["color"] = {"explorer": "#5fa85f", "rl": "#c88a3a", "human": "#c0507f"}.get(snap.kind, "#5a8fd6")
    out["sees"] = list(snap.sees.rows or [])[:12]
    t = snap.thinking
    out["text"] = [f"{t.want} | {t.plan or t.blocker}", f"{t.driver} {t.rule} {t.button}->{t.result}",
                   t.brain, f"seg {snap.segment.id} goals {len(snap.goals)}"]
    out["text"] = [x for x in out["text"] if x]
    return out


def _data(model: ViewerModel) -> bytes:
    return json.dumps({"agents": [_agent_json(model, aid) for aid in model.ids()]}).encode()


def make_server(model: ViewerModel, port: int = 8899, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # read-only: no do_POST/do_PUT anywhere
            path = urlparse(self.path).path
            q = parse_qs(urlparse(self.path).query)
            if path == "/":
                return self._send(200, "text/html; charset=utf-8", _PAGE.encode())
            if path == "/data":
                return self._send(200, "application/json", _data(model))
            if path == "/frame.png":
                aid = (q.get("id") or [""])[0]
                fr = model.frame(aid)
                if fr is None:
                    return self._send(404, "text/plain", b"no frame")
                rgb, w, h = fr
                scale = int((q.get("scale") or ["3"])[0])
                return self._send(200, "image/png", pres.frame_png(rgb, w, h, scale=max(1, scale)))
            return self._send(404, "text/plain", b"not found")

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def serve_threaded(model: ViewerModel, port: int = 8899) -> ThreadingHTTPServer:
    httpd = make_server(model, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
