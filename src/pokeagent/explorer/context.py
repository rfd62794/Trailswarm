"""ExplorerContext: everything the demo's ``st`` dict held, as named fields, plus the live handles.

Behaviours read and write the context; nothing else carries state between steps. ``get`` / ``setdefault`` /
``__setitem__`` are a thin dict-protocol shim so ``goals.check_goals(emu, ctx)`` (which was written against
the ``st`` dict and is shared with other tools) keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import BATTLE_FLAG, TILEMAP, TILEMAP_LEN, box_open, frame_lines
from pokeagent.goals import check_goals
from pokeagent.ram import read_state


@dataclass
class ExplorerOptions:
    """The CLI flags the policy reads (``a.<flag>`` in the old closure)."""

    starter: str = "any"
    state_stem: str = ""  # Path(--state).stem, "" when no state
    steps: int = 300
    stop_at_goal: str | None = None
    stop_at_map: int | None = None  # sub-segment runs end on first entry into this map id
    headless: bool = False
    box_pace: int = 6
    frames_per_step: int = 10
    train_level: int = 8
    maps_path: str = "runs/maps.json"
    adaptive_pace: bool = False  # A through text boxes at the learned pace (text_press) instead of the fixed settle
    fast_text: bool = False  # run the set_text_speed_fast procedure once at the start
    bandit: bool = False  # behaviour bandit overrides the Explorer at three decision points (pokeagent.bandit)
    bandit_path: str = "runs/bandit.json"  # shared table the bandit loads at start
    bandit_delta: str = ""  # where this run's delta goes ("" = <run_dir>/bandit_delta.json)
    role: str = ""  # swarm role ("explorer" / "exploiter" / ...); only "explorer" is steered and paid by novelty
    novelty: bool = False  # track global novelty + discoveries (pokeagent.novelty); bonuses reach only role == "explorer"
    novelty_path: str = "runs/novelty.json"
    novelty_runs: str = "runs"  # the runs directory the discovery log and its review saves go under
    novelty_delta: str = ""  # where this run writes its novelty delta ("" = <run_dir>/novelty_delta.json)
    item_tms: bool = False  # explorer/item_policies: teach TMs too (off: HMs only)
    drill_grind: int | None = None  # grind drill: the map id whose grass the GrindDrill behaviour paces (pokeagent.grind.drill)
    par_follow: bool = False  # plan_goal's route is walked along the ROM par path (pokeagent.explorer.par_follow)


@dataclass
class Frame:
    """One step's read-only snapshot of the screen (nothing changes between reads inside a step)."""

    m: int = 0
    x: int = 0
    y: int = 0
    tm: bytes = b""
    box: bool = False
    lines: list[str] = field(default_factory=list)
    battling: bool = False  # wIsInBattle != 0, or a FIGHT line on screen


@dataclass
class ExplorerContext:
    emu: Any
    mem: MapMemory
    opts: ExplorerOptions = field(default_factory=ExplorerOptions)
    log: Callable[..., None] = lambda text, tag=None: None
    run_dir: Path = Path(".")
    anomalies: Any = None  # explorer.anomalies.AnomalyMonitor (None = anomaly detection off)
    leg_saver: Any = None  # legs.states.LegStateSaver (--save-leg-states): saves a state on each calm map entry
    drill: Any = None  # legs.drill.DrillMonitor / grind.drill.GrindDrillMonitor: ends a drill run and records drill_result
    ram_diff: Any = None  # explorer.ram_diff.RamDiffer (None = event RAM diffs off)
    trans: Any = None  # open transitions.jsonl handle (the demo's per-press log)
    # --- the old st dict, field by field (defaults are what the old st.get(..., default) calls used) ---
    step: int = 0
    frame: int = 0
    photo: Any = None
    paused: bool = False
    done: bool = False
    facing: str = "DOWN"
    last_fail: tuple | None = None
    box_streak: int = 0
    settle: int = 0
    inter: dict | None = None
    goal_steps: dict = field(default_factory=dict)
    stable_frames: int = 0
    explore_run: bool = False
    speed: int = 1
    a_pos: tuple | None = None
    a_streak: int = 0
    all_pp_out: int = 0
    battle_pos: tuple | None = None
    battles: int = 0
    battles_won: int = 0
    beat: dict | None = None
    beat_sig_done: str | None = None
    battle_log: dict | None = None
    best_level_seen: int = 0
    box_open_now: bool = False
    burst_maps: set = field(default_factory=set)
    catch_attempt: dict | None = None
    catch_mode: bool = False
    readiness_note: str = ""  # last party-readiness verdict logged (plan_goal)
    stage_goal: str | None = None  # current stage goal (training.stage_goal), published by plan_goal each step
    clamp_note: str = ""      # last readiness clamp logged
    under_level_note: str = ""  # last under-level line logged (plan_goal)
    blackouts_row: int = 0    # lost battles that warped us away since the last win (grind budget)
    grind: Any = None         # explorer.grind.GrindBudget, made on first use
    dialog: list = field(default_factory=list)
    declined_balls: dict = field(default_factory=dict)  # (map, x, y, facing) of a ball whose starter offer we said NO to -> species
    episode: dict | None = None
    events_prev: bytes | None = None
    exp_prev: int | None = None
    stat_exp_prev: int | None = None
    explore_burst: int = 0
    forget_move: str | None = None
    frontier_at: tuple | None = None  # position the committed route's next button was chosen at
    frontier_route: list = field(default_factory=list)  # buttons left to the committed frontier_target
    frontier_target: tuple | None = None  # (map, x, y) frontier tile the frontier behaviour is committed to
    goal_left_house: bool = False
    goto: list | None = None
    had_parcel: bool = False
    in_battle: bool = False
    initial_goals: set = field(default_factory=set)
    initial_goals_ready: bool = False  # the old code tested '"initial_goals" in st'
    known_maps_at_start: set | None = None
    last_battle_hp: int | None = None
    last_dir: str | None = None  # direction of the last press that moved the player (choose()'s reverse penalty)
    last_hash: int | None = None
    last_move_choice: str | None = None
    last_press: str | None = None
    last_sig: tuple | None = None
    last_text: str = ""
    mash: int = 0  # decisions spent in the current busy stretch (Readiness)
    busy_presses: int = 0  # A/B nudges in the current busy stretch
    busy_start: int = 0  # ctx.frame when the stretch began
    busy_sig: str = ""  # the situation signature of the stretch
    busy_strategy: str = ""  # the mash_skill strategy chosen for it
    busy_last_press: int = 0  # ctx.frame of the last nudge
    skill: object = None  # MashSkill, built lazily over mem.data
    mom_failed_until: int = 0
    talk_closed_frame: int = -1  # ctx.frame when the last interaction's box closed (post_talk_settle)
    post_talk_waits: int = 0
    setup_steps: int = 0  # presses spent on one-time setup (the text speed procedure), not counted in ctx.step
    box_empty_since: int = -1  # ctx.frame when the current empty-box stretch began
    box_empty_waits: int = 0  # consecutive no-press turns spent on an empty text box (box_settle)
    pace: object = None  # text_pace.PaceLearner, built lazily over mem.data
    text_frames: int = 0  # emulator frames spent pressing through text boxes (fast path only)
    btw_hash: int = 0  # battle_text_wait: hash of the page on screen
    btw_since: int = 0  # ctx.frame when that page last changed
    btw_waits: int = 0
    restock: dict = field(default_factory=dict)  # Poke Ball restock state (explorer/restock.py): intent, tries, steps, failed Marts
    catch_want: tuple = (None, None)  # ((battle no., species), reason from catch_list.catch_wanted or None) for the current fight
    heal_trips: int = 0  # Pokecenter entries this run (area_grind bounds the 90% top-off trips)
    last_plan_map: int = -1
    area_grind: dict = field(default_factory=dict)  # steps / battles spent grinding in place on Route 2 / the Forest, and whether it was lifted
    train_need: int = 8  # the training level plan_goal last computed for this map (0 inside a dungeon)
    buy_skipped: bool = False  # the buy_magikarp stage ran out of steps (BUY_STEP_CAP): settled for this run
    buy_steps: int = 0  # steps spent in or around the Mt Moon Pokemon Center with buy_magikarp open
    cut_learner_steps: int = 0  # steps spent with hm01_cut met and cut_learner still open (plan_goal)
    cut_learner_skipped: bool = False  # the learner stage ran out of steps (LEARNER_STEP_CAP): settled for this run
    learner_target: Any = None  # knowledge.cut_learner.LearnerTarget the learner_hunt walk heads for
    hunt_grass: bool = False  # on the learner target's map: frontier should seek grass for the wild encounter
    switch_runs: tuple = (-1, 0)  # (ctx.battles, RUN attempts) of switch_train_run
    party_order: dict | None = None  # reorder_party in progress: {"src", "presses", "wait"}
    order_retry_at: int = 0  # step before which a failed reorder_party is not retried
    switch_train: dict | None = None  # switch_out_lead in progress for this battle
    switch_gave_up: int = -1  # ctx.battles value of the battle whose switch was abandoned
    magikarp_shared: int = 0  # battles in which the trainee was sent out and swapped on turn one
    gyarados_steps: int = 0  # steps with gyarados the next unmet goal and a Magikarp in the party
    gyarados_idle: int = 0  # consecutive plan steps at the gyarados stage with the training gate closed or lifted
    gyarados_skipped: bool = False  # GYARADOS_STEP_CAP spent: the gyarados goal is settled for this run
    train_member: int | None = None  # party slot team_readiness names as the shortfall (None when the team is ready)
    team_note: str = ""  # last team-readiness verdict logged (plan_goal)
    center_intent: str | None = None  # why we are inside a Pokecenter on purpose (heal, PC, a purchase goal); the planner will not walk out while set
    mom_talk_hp: int = 0
    mom_talk_step: int | None = None
    move_nav: int = 0
    move_reason: str = ""
    no_pp: set = field(default_factory=set)
    pending_move: dict | None = None
    pending_effect: dict | None = None  # our landed attack still awaiting its result message (battle text)
    fx_src: list | None = None  # battle-text scan cursor: the dialog list object last scanned ...
    fx_seen: list = field(default_factory=list)  # ... and a snapshot of its entries already parsed
    fx_last: dict | None = None  # last 'used' event seen {'side': 'ours'|'enemy', 'move': name}
    fx_last_fx: dict | None = None  # last result message attributed to our move {'move', 'effect', 'step'}
    move_tag: str = ""  # rule string of the last/target move ('EMBER x2 FIRE>GRASS/POISON STAB')
    pos_hist: list = field(default_factory=list)
    potion_hp_before: int | None = None
    heal_item: int = 0x14  # heal item the current battle use / top-up sequence is working on (economy.heal_items)
    rom_route: dict = field(default_factory=dict)  # cave_route's cached ROM path + bump counters (this run only)
    ship_plan: Any = None  # atlas.walkgrid.rom_cave_planner over the dock + S.S. Anne maps (ship_gate walk-off); set by the demo
    cave_plan: Any = None  # atlas.walkgrid.rom_cave_planner(): multi-floor ROM route; set by the demo
    ladders: Any = None  # cave_route.rom_ladders(): (map, dest_map) -> ROM-header warp tiles; set by the demo
    cave_catch_balls: dict = field(default_factory=dict)  # species -> balls thrown this run (battle_run caps it inside dungeons)
    topup_presses: int = 0  # presses in the current cave_topup potion sequence (0 = not started)
    topup_potions0: int = 0
    topup_cooldown_until: int = 0
    cave_runs: int = 0  # RUN presses chosen only because we are in a dungeon, this battle (battle_run caps it)
    dir_fail: int = 0  # consecutive direction presses that left the position unchanged (LoopGuard)
    dir_fail_pos: tuple | None = None
    rope_presses: int = 0  # presses spent in the current escape-rope sequence (cave_escape); 0 = not started
    rope_cooldown_until: int = 0  # step before which a failed rope try is not repeated
    item_attempts: int = 0  # item-list confirmations this battle (item_use.MAX_ITEM_ATTEMPTS caps it)
    item_blocked: set = field(default_factory=set)  # item ids that cannot help this battle ("won't have any effect")
    proc: dict | None = None
    proc_done: set = field(default_factory=set)
    proc_due: list = field(default_factory=list)
    recent_tiles: dict = field(default_factory=dict)  # map -> last TABU_LEN (x, y) stood on (choose()'s tabu)
    replay: list = field(default_factory=list)
    replay_ctx: dict | None = None
    replayed_here: tuple | None = None
    seen_maps: set = field(default_factory=set)
    shake: int = 0
    shake_goals_150: tuple | None = None
    shakes: int = 0
    slow_until: int = 0
    stall: int = 0
    stalls: int = 0
    yesno: dict | None = None
    already_out_until: int = 0  # step until which the active mon's party slot is off limits ("<name> is already out!" just showed)
    pickup_await: tuple | None = None  # (map,x,y) ball whose A press is awaiting its item result
    pickup_ball: tuple | None = None  # committed item-ball target (map,x,y)
    ball_result: tuple | None = None  # (map,x,y,item|None): the last item-ball dialog to close, from press_interact
    pickup_gone: set = field(default_factory=set)  # (map,x,y) balls seen hidden or collected this run
    pickup_approach: dict = field(default_factory=dict)  # (map,x,y) -> presses spent walking through unexplored ground toward it
    pickup_last: tuple | None = None  # (map,x,y, ball) where the last pickup walking press was made
    pickup_stuck: int = 0  # consecutive pickup walking presses that left the player where they were
    pickup_tries: dict = field(default_factory=dict)  # (map,x,y) -> presses that gave no item text this run
    trainer_npc: dict | None = None  # the npc entry marked trainer by the current trainer battle
    # --- per-step scratch, rebuilt by refresh() / the battle behaviour ---
    view: Frame = field(default_factory=Frame)
    bv: Any = None  # the battle behaviour's read of the current battle (behaviours.battle.BattleView)
    party_log: Any = None  # explorer.party_log.PartyLog, made on first use (XP/level logging)
    econ: Any = None  # explorer.economy.ledger.Ledger, made on first use (income/spend/blackouts, Pokecenters visited)
    shop_intent: Any = None  # ("mart", map|None) while restock walks to a Mart: par_follow treats the trip as a "mart" trip
    bandit: Any = None  # pokeagent.bandit.driver.BanditDriver (None = bandit off: every hook answers as the Explorer would)
    novelty: Any = None  # pokeagent.novelty.tracker.NoveltyTracker (None = novelty off: nothing below changes)
    item_seq: dict | None = None  # behaviours/use_items.py: the item-use sequence in progress (item, kind, presses, before snapshot ...)
    item_next_check: int = 0  # step before which use_items does not re-evaluate its policies
    item_cooldown: dict = field(default_factory=dict)  # item id -> step before which use_items does not try it again
    goal_talk_tries: dict = field(default_factory=dict)  # goal id -> A presses made by behaviours/goal_talk.py at the goal's person
    item_notes: set = field(default_factory=set)  # one-time use_items log notes already printed (e.g. an HM with no learner in the party)
    xitem: dict | None = None  # item_policies.xitems_battle: this battle's X-item decision {battle, item, count0}
    par: Any = None  # explorer.par_follow.ParState, created on first use when opts.par_follow is on

    # --- dict-protocol shim for goals.check_goals ---
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not hasattr(self, key):
            setattr(self, key, default)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def pop(self, key: str) -> Any:
        """Take a one-shot field's value and reset it to None (the old ``st.pop(key, None)``)."""
        value = getattr(self, key)
        setattr(self, key, None)
        return value

    # --- reads ---
    def pos(self) -> tuple[int, int, int]:
        s = read_state(self.emu)
        return (s.map_id, s.x, s.y)

    def goals(self) -> dict[str, bool]:
        return check_goals(self.emu, self)

    def refresh(self) -> Frame:
        """Snapshot the screen for this step: position, tile map, open box, on-screen lines, battle."""
        m, x, y = self.pos()
        tm = self.emu.read_range(TILEMAP, TILEMAP_LEN)
        box = box_open(tm)
        lines = frame_lines(tm) if box else []
        battling = self.emu.read(BATTLE_FLAG) != 0 or any("FIGHT" in ln for ln in lines)
        self.view = Frame(m, x, y, tm, box, lines, battling)
        return self.view
