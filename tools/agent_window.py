"""Windowed agent runner: every step drawn in its own tk window, like the demo did.

    uv run python tools/agent_window.py --policy q --segment left_house --speed 8

An agent = process + emulator + policy + this local display. The window is
owned by the process (closeable, positionable, status line) — no SDL, no
transport, no skipped frames. Headless learners do the bulk training; run one
or a few of these windows to watch learning happen. N agents = N windows.
"""
from __future__ import annotations

import argparse
import random
import tkinter as tk
from collections import defaultdict

from PIL import Image, ImageTk

from rl_env import ACTIONS, GOAL_FNS, SEGMENT_STATES, SegmentEnv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", default="left_house", choices=sorted(GOAL_FNS))
    ap.add_argument("--policy", default="q", choices=["q", "random"])
    ap.add_argument("--episodes", type=int, default=300)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--speed", type=float, default=8.0, help="env steps per second (8 ~ realtime feel)")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default=None, help="override segment start state")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    env = SegmentEnv(a.rom, a.state or SEGMENT_STATES[a.segment], GOAL_FNS[a.segment],
                     max_steps=a.max_steps)
    Q: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * len(ACTIONS))
    alpha, gamma = 0.2, 0.99

    root = tk.Tk()
    root.title(f"PokeAgent {a.policy} — {a.segment}")
    lab = tk.Label(root)
    lab.pack()
    txt = tk.Label(root, font=("Consolas", 10), anchor="w")
    txt.pack(fill="x")

    st = {"eps_done": 0, "wins": 0, "steps": [], "closed": False}
    photo = {"img": None}
    obs = env.reset()

    def draw() -> None:
        im = Image.frombytes("RGB", (160, 144), env.emu.frame_rgb())
        photo["img"] = ImageTk.PhotoImage(im.resize((160 * a.scale, 144 * a.scale), Image.NEAREST))
        lab.configure(image=photo["img"])
        best = min(st["steps"]) if st["steps"] else "-"
        txt.configure(text=f"ep {st['eps_done']}  step {env.steps}  pos {obs}  "
                           f"wins {st['wins']}  best {best}")

    def tick() -> None:
        nonlocal obs
        if st["closed"] or st["eps_done"] >= a.episodes:
            return
        eps = max(0.0, 1.0 - st["eps_done"] / max(1, a.episodes))  # epsilon decays over training
        act = (rng.randrange(len(ACTIONS)) if a.policy == "random" or rng.random() < eps
               else max(range(len(ACTIONS)), key=lambda i: Q[obs][i]))
        nxt, rew, done, _ = env.step(act)
        q = Q[obs]
        q[act] += alpha * (rew + gamma * max(Q[nxt]) - q[act])
        obs = nxt
        if done:
            if env.goal_fn(env.emu):
                st["wins"] += 1
            st["steps"].append(env.steps)
            st["eps_done"] += 1
            obs = env.reset()
        draw()
        root.after(int(1000 / max(0.1, a.speed)), tick)

    def close() -> None:
        st["closed"] = True
        env.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    draw()
    root.after(0, tick)
    root.mainloop()
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
