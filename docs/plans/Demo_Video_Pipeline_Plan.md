# Plan: the harness records its own demo videos

Status: draft, 2026-11-08. Approved by Robert. Held until phase 6 of `Multi_Game_Framework_Plan.md` lands.

## Goal

A long-form narrated widescreen video of an agent playing, showing the game view, a world or progress view and
the decision making together, written from what actually happened in the run. Shorts are cut from the same
recording. Nothing appears on Robert's screen during capture.

## What exists

- World view: `tools/make_world_gif.py` replays a run headless from `transitions.jsonl`.
- Decisions: `decisions.jsonl` logs behaviour, rule, button and goal stage per step; `transitions.jsonl` logs
  on-screen text.
- Game frames: the run loop publishes them live, but past runs saved none.
- RFD_YT_Engine: a beat file points at any video and adds timed clips, narration, music and an outro. The assembly
  code found so far only builds vertical Shorts. Text-to-speech defaults to Windows voices, with Edge neural available.

## Constraints

- The game view must be captured during the run. Past runs have no footage, and the replay tool only expects a
  stall to reproduce within a margin, so re-running is not a substitute.
- Build on the frame-sharing layout from PR #167.
- The World view is Kanto-only, so panels are swappable. A platformer gets a level-progress strip.
- Capture runs on the laptop. The Office Tower does no YouTube work.
- No window or OS input on Robert's display.

## Pieces

| # | Piece | Who | Done when |
|---|---|---|---|
| 1 | Recorder: frames saved during the run, keyed by step | Devin | a run produces frames whose steps match the decision log |
| 2 | Compositor: game, world or progress, and decision panels into one widescreen video, with speed ramping | Devin | one video from one recorded run, no window opened |
| 3 | Moments and script: a model drafts narration from the logs, each line citing its step range | Claude | every claim traces to a log line; passes the content frame and fact-check |
| 4 | Long-form assembly in RFD_YT_Engine: narrated 16:9 path | Devin | a long-form render from one beat file |
| 5 | First video: PokeAgent, one featured agent, private upload | Claude runs, Robert releases | private video exists |

## Decisions already made

- Draft narration with neural text-to-speech. Robert may re-record the final.
- PokeAgent first. Kirby follows once its ROM exists.
- Publishing stays Robert's. Uploads are private until he releases them.
- Published footage follows `docs/LEGAL.md`: lawfully held copies only, real commentary, and each publisher's video rules checked per game.
- The engine's open items still apply: OAuth re-login, the end-to-end private publish, and the 35 renders to review.
