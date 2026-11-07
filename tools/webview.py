"""Lightweight web viewer: live frames + status + brain line per seat.

    uv run python tools/webview.py            # http://localhost:8899
"""
from __future__ import annotations

import glob
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from pokeagent.qdecode import brain_line
from pokeagent.qmodels import load_model
from pokeagent.telemetry import FrameSubscriber

PORTS = list(range(8890, 8896))
subs = {}
brain_cache = {}
PAGE = """<!doctype html><meta http-equiv=refresh content=1><style>
body{background:#111;color:#ddd;font:13px monospace}img{width:320px;image-rendering:pixelated}
.t{display:inline-block;margin:8px;vertical-align:top}</style>
<h3>PokeAgent swarm <span id=t></span></h3><div id=s></div>
<script>setInterval(async()=>{const r=await fetch('/data').then(x=>x.json());document.getElementById('s').innerHTML=r.map(a=>`<div class=t><img src=/f/${a.p}?${Date.now()}><div>${a.l}</div><div style=color:#8f8>${a.b||''}</div></div>`).join('')},1000)</script>"""


def sub(p):
    if p not in subs:
        subs[p] = FrameSubscriber(p, root=Path(__file__).resolve().parents[1])
    return subs[p]


def status(p):
    f = Path(f'runs/rlstatus_{p}.json')
    if not f.exists():
        return f':{p} offline', ''
    s = json.loads(f.read_text())
    ev = (s.get('evaluation') or {})
    line = (f":{p} {s.get('tag','')} {s.get('phase','TRAIN')} ep {s.get('episode','?')} "
            f"wins {s.get('wins',0)} eval {ev.get('wins','-')}/{ev.get('episodes','-')}")
    brain = ''
    try:
        qs = sorted(glob.glob(f'runs/**/q_{p}*.json', recursive=True),
                    key=lambda x: Path(x).stat().st_mtime)
        ts = sorted(glob.glob(f'runs/traces/*_{p}.jsonl'), key=lambda x: Path(x).stat().st_mtime)
        if qs and ts:
            qp, mt = qs[-1], Path(qs[-1]).stat().st_mtime
            if brain_cache.get(qp, [0])[0] != mt:
                d = json.loads(Path(qp).read_text())
                brain_cache[qp] = [mt, load_model(qp, d.get('schema'), d.get('actions', 6)), d.get('actions', 6)]
            rec = json.loads(Path(ts[-1]).read_text().strip().splitlines()[-1])
            obs = tuple(rec.get('final_obs') or (rec.get('path') or [[None]])[-1][:-1])
            brain = brain_line(brain_cache[qp][1], obs, brain_cache[qp][2])
    except Exception:
        pass
    return line, brain


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/f/'):
            p = int(self.path[3:].split('?')[0])
            fr = sub(p).read()
            if fr:
                im = Image.frombytes('RGB', (160, 144), bytes(fr[0])).resize((320, 288), Image.NEAREST)
                b = io.BytesIO(); im.save(b, 'PNG')
                self.send_response(200); self.send_header('content-type', 'image/png'); self.end_headers()
                self.wfile.write(b.getvalue()); return
            self.send_response(404); self.end_headers(); return
        if self.path.startswith('/data'):
            out = [{'p': p, 'l': status(p)[0], 'b': status(p)[1]} for p in PORTS]
            b = json.dumps(out).encode()
            self.send_response(200); self.send_header('content-type', 'application/json'); self.end_headers()
            self.wfile.write(b); return
        self.send_response(200); self.send_header('content-type', 'text/html'); self.end_headers()
        self.wfile.write(PAGE.encode())

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8899), H).serve_forever()
