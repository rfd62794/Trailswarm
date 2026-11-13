# AI-plays-Pokemon agents: standards, survivors and takedowns (2026-11-12)

## 1. Scope and the job
Whole Trailswarm repo plus the public-content plan (video, screenshots, maybe YouTube). Job: a solo builder shows a rule-based Pokemon Red agent publicly without losing the repo or channel. "Better" = watchable and legally boring. Not legal advice. Claims marked (unverified) lacked a primary source.

## 2. What we do today
- Rule/behaviour explorer, RAM + ROM-table state, no model per step: `src/pokeagent/explorer/behaviours/`; 128-goal RAM-detector ladder: `src/pokeagent/data/campaign.json`, `docs/campaign_goals.md`.
- Savestate segment curriculum, continuous swarm with shared map memory: `docs/SEGMENTS.md`, `tools/swarm.py`; real-ROM hands-off runs skip without `POKEAGENT_ROM`.
- Dear PyGui World view and `docs/media/world.gif` (ROM-rendered map, trails); results with dates: `docs/RESULTS.md`; negative results logged: `EXPLORATION.md`.
- ROM rule: no ROM, firmware or sources in repo; user supplies own copy; media removed on request; footage only from lawful copies, with commentary, per current Nintendo rules: `docs/LEGAL.md`. Save states allowed (Robert, 2026-11-08).

## 3. Industry standard (how the survivors build and publish)
- Claude Plays Pokemon (Anthropic, Feb 2025): screen pixels, "basic memory" and button-press function calls ([Anthropic, 2025-02-24](https://www.anthropic.com/research/visible-extended-thinking)); knowledge base plus a critic Claude, run by an employee on Twitch ([LessWrong, 2025-03-07](https://www.greaterwrong.com/posts/HyD3khBjnBhvsp8Gb/so-how-well-is-claude-playing-pokemon)). Shown as a milestone-vs-actions chart.
- Gemini Plays Pokemon (independent dev JoelZ, 2025): Blue finished May 2025; paper shows frame plus ASCII text map, notepad, later self-built tools; a human refined the harness during the livestream ([arXiv 2605.09998, May 2026](https://arxiv.org/html/2605.09998v1); [Ars via Harvard TagTeam, May 2025](https://tagteam.harvard.edu/hub_feeds/3382/feed_items/13730590)).
- PokemonRedExperiments (Whidden, MIT): README says use a "legally obtained" ROM, gives its SHA-1, never ships it, ships `.state` files, TensorBoard plus a live shared map broadcast ([GitHub](https://github.com/PWhiddy/PokemonRedExperiments)); 33-min video, 2023-10-08, millions of views (counts vary by source) ([TechCrunch, 2023-10-18](https://techcrunch.com/2023/10/18/after-50000-hours-this-ai-can-play-pokemon-red)).
- PokeAgent Challenge (NeurIPS 2025, paper Mar 2026): Emerald speedrun track scores completion % over 15 milestones, then time, then action count; baseline uses MCP tools (A*, buttons, knowledge) ([arXiv 2603.15563](https://arxiv.org/html/2603.15563)). pokemonred_puffer: reward classes in config, map visualizer wrapper ([GitHub](https://github.com/drubinstein/pokemonred_puffer)).

## 4. Common use cases
- Long-horizon LLM benchmark (Claude, Gemini, PokeAgent). Gemini's own developer says Pokemon is ill-suited as a reliable benchmark ([Ars, 2025-05](https://tagteam.harvard.edu/hub_feeds/3382/feed_items/13730590)).
- RL from RAM-shaped reward on many headless emulators (Whidden, pokemonred_puffer).
- Battle-only agents on Showdown (no ROM): PokeLLMon 49% ladder win rate ([arXiv 2402.01118, Feb 2024](https://arxiv.org/abs/2402.01118v1)); PokeChamp, 3M-game dataset ([arXiv 2503.04094, Mar 2025](https://arxiv.org/abs/2503.04094)).
- Crowd play: Twitch Plays Pokemon, Feb 2014, anonymous, Game Award Dec 2014; no Nintendo statement found ([Wikipedia](https://en.wikipedia.org/wiki/Twitch_Plays_Pok%C3%A9mon)).

## 5. Similar use cases (legal history; who was hit)
- Emulators: Yuzu/Citra, $2.4M settlement, Mar 2024, DMCA anti-circumvention claim ([Engadget](https://www.engadget.com/makers-of-switch-emulator-yuzu-quickly-settle-with-nintendo-for-24-million-203204698.html)); Ryujinx ended 2024-10-01 after Nintendo contact, no lawsuit ([Heise](https://heise.de/-9960236)); Dolphin Steam release dropped 2023, Valve/Nintendo letter, dispute over a formal DMCA notice ([HotHardware](https://hothardware.com/news/dolphin-emulator-devs-explain-steam-ban-insists-nintendo-never-sent-takedown-notice)); 400+ Switch emulator GitHub repos removed ([VGC](https://videogameschronicle.com/news/nintendo-wipes-out-400-more-switch-emulator-repositories-on-github-as-it-continues-its-fight-on-piracy)).
- ROM sites: RomUniverse $2.1M judgment, 2021, later ordered to destroy files; LoveROMS lost 2018 ([MobileSyrup, 2021-06-01](https://mobilesyrup.com/2021/06/01/nintendo-awarded-2-1-million-in-damages-romuniverse-pirated-game-lawsuit/)).
- Fan games: Uranium (about 1.5M downloads) pulled Aug 2016 after takedowns; AM2R DMCA 2016; Prism C&D Dec 2016 (reports differ) ([PC Gamer](https://www.pcgamer.com/uk/illegal-and-important-the-catch-22-of-pc-fan-games/); [Nintendo Life, 2016-08](https://www.nintendolife.com/news/2016/08/fan-made_title_pokemon_uranium_withdrawn_by_creators_following_cease_and_desist_fears)). Tools: Pokemon Essentials takedown 2018 ([Nintendo Life](https://www.nintendolife.com/news/2018/08/nintendo_enforces_takedown_of_fan-made_game_creator_pokemon_essentials)).
- AI/RL Pokemon projects: no takedown found in any search (absence of evidence, not a clearance).

## 6. Comparison table
| Flow | Ours | Standard / Common | Verdict |
|---|---|---|---|
| ROM | User-supplied, never shipped (LEGAL.md) | Same; Whidden adds SHA-1 check | Matches; gap: no hash line in README |
| Observation | RAM + ROM tables, no pixels | LLM harnesses: pixels + text map; RL: mixed | Deliberate (reliable, cheap) |
| Progress metric | 128-goal ladder, steps | PokeAgent: milestone %, then time, then actions | Gap: no single published score |
| Map/memory | Shared learned map, merged across swarm | Notepad/KB (LLM); static maps | Better (see report) |
| Savestates | Segment checkpoints; may publish | Whidden ships `.state`; puffer has `pyboy_states` | Matches |
| Show progress | World view, gif | Whidden live map web viz, TensorBoard | Gap: nothing shareable on the web |
| Footage | Lawful copy, commentary, rules checked | Claude on Twitch (corporate); Whidden video | Matches; risk below |
| Failure reporting | RESULTS/EXPLORATION log negatives | Claude posts show loops openly | Matches |

## 7. Ranked recommendations
1. Add the expected ROM SHA-1 and "supply your own legally obtained copy" to README, no source named (row ROM; Whidden README). Cheapest.
2. Publish one score per run: goals reached, then steps, then actions, copied from the PokeAgent order, in `tools/status.py` and RESULTS (row Progress metric).
3. Make video commentary-first: our World view, charts and run stats as the picture; keep the raw emulator window and any "how to emulate" talk off screen. Nintendo's guidelines (updated 2024-09-02) give emulators as an example of circumvention software in inappropriate content and allow only Nintendo-specified monetization ([Nintendo](https://www.nintendo.co.jp/networkservice_guideline/en/index.html)); so no monetization at launch, and treat strikes as a risk, not a clearance (row Footage; section 5).
4. Static web replay of the trails map, own-rendered, like Whidden's pokerl-map-viz; keep the takedown-on-request line (row Show progress).
5. Publish dated negative results and stuck points in the Claude-stream style, with seeds so runs reproduce (row Failure reporting).

Do not copy: a ROM or any download pointer (RomUniverse, Uranium); emulator-circumvention how-tos (Yuzu, Dolphin Common Key); an LLM call per step (cost); monetized live streams; standalone game-asset packs. Optional, low priority: publish a bedroom save state. On 2026-11-13 the bytecheck tool (PR #230) scanned the six committed fixture states against the real ROM. All six were CLEAN under the save-state policy: ROM-matching coverage was 0.16-0.61% and the longest matching run was 663 bytes, which is likely tile graphics copied into VRAM. Rule: any state published must first pass `pokeagent bytecheck` under the state policy.

## 8. Sources
All links inline above, accessed 2026-11-12. Primary: Nintendo guidelines, Anthropic post, arXiv 2603.15563 / 2605.09998 / 2402.01118 / 2503.04094, Whidden and puffer READMEs. Secondary (news): Engadget, Heise, HotHardware, VGC, MobileSyrup, PC Gamer, Nintendo Life, TechCrunch. Not verified: Whidden's current view count, Prism's exact date, any official Nintendo statement on Twitch Plays Pokemon or AI agents.
