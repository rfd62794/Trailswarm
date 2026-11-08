"""Text renderers: one function per review tool, plus the shared emit/error helpers.

Every renderer consumes the same dict ``--json`` prints, so the two outputs always agree.
"""
from __future__ import annotations

import json


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True)


def emit(obj, json_out: bool, text: str) -> None:
    print(dumps(obj) if json_out else text)


def error(msg: str, json_out: bool) -> int:
    """One-line usage/missing-input error; always exit 2."""
    emit({"error": msg}, json_out, f"error: {msg}")
    return 2


def _fmt_event(e: dict) -> str:
    k = e["kind"]
    if k == "goal":
        return f"goal {e.get('goal')}" + (f" frame={e['frame']}" if e.get("frame") is not None else "")
    if k == "map":
        return f"map {e.get('from')} -> {e.get('to')}"
    if k == "map_bounce":
        return f"map_bounce {e.get('map_a')}<->{e.get('map_b')} x{e.get('count')} ({e.get('presses')} presses)"
    if k == "battle":
        return (f"battle kind={e.get('battle_kind')} outcome={e.get('outcome')} "
                f"enemy={e.get('enemy_species')} hp_delta={e.get('hp_delta')} turns={e.get('turns')}")
    if k == "wild_battles":
        return f"wild_battles count={e.get('count')} wins={e.get('wins')}"
    if k == "blackout":
        return f"blackout enemy={e.get('enemy_species')} respawn_map={e.get('end_map')}"
    if k in ("heal", "buy"):
        return f"{k} rule={e.get('rule')} presses={e.get('presses')}"
    if k == "stall":
        return f"stall {e.get('likely_cause')} [{e.get('signature_key')}]"
    if k == "loop":
        return f"loop {e.get('loop_kind')} presses={e.get('presses')} rule={e.get('rule')} key={e.get('key')}"
    if k == "level":
        ch = ", ".join(f"#{c['species']} L{c['level_from']}->{c['level_to']} (+{c['exp_gain']}xp)"
                       for c in e.get("changes", []))
        return f"level {ch}"
    return f"{k} {json.dumps(e, sort_keys=True)}"


def run_text(s: dict) -> str:
    h = s["header"]
    seg = h["segment"]
    lines = [f"run {s['run']}" + (f"  ({s['start_time']})" if s.get("start_time") else "")]
    lines.append(f"  segment tag={seg['tag']} stop_at_goal={seg['stop_at_goal']} stop_at_map={seg['stop_at_map']}")
    lines.append(f"  start={h['start']} starter={h['starter']} seed={h['seed']} git_sha={h['git_sha']}")
    lines.append(f"  steps {h['steps']}/{h['budget']}  presses_by_source={h['presses_by_source']}"
                 + (f"  frames={h['frames']}" if h.get("frames") is not None else ""))
    if s.get("skipped_rows"):
        lines.append(f"  skipped_rows: {s['skipped_rows']}")
    lines.append("events:")
    for e in s["events"]:
        lines.append(f"  @{e.get('step')} {_fmt_event(e)}")
    if s.get("events_omitted"):
        lines.append(f"  ... {s['events_omitted']} more events omitted by --max-events")
    if s["loops"]:
        lines.append("loops:")
        for e in s["loops"]:
            lines.append(f"  {e['kind']} steps {e['step']}..{e['end_step']} presses={e['presses']}"
                         f" rule={e['rule']} key={e['key']}")
    lines.append("decisions by rule:")
    for r in s["rules"]:
        lines.append(f"  {r['rule']} ({r['behaviour']}) presses={r['presses']} share={r['share']:.0%}")
    if s["unclassified_rules"]:
        lines.append("unclassified rules: " + ", ".join(r["rule"] for r in s["unclassified_rules"]))
    lv = s["levels"]
    if lv["first"] is not None:
        lines.append(f"levels: first={lv['first']} last={lv['last']}")
        for g in lv["gains"]:
            lines.append(f"  #{g['species']} L{g['level_from']}->{g['level_to']} exp+{g['exp_gained']}")
    end = s["end"]
    lines.append(f"end (inferred): {end['reason']}" + (f" also={end['also']}" if end["also"] else "")
                 + f" last_step={end['last_step']} pos={end['position']}")
    if s["breaks"]:
        lines.append("BREAKS: " + "; ".join(json.dumps(b, sort_keys=True) for b in s["breaks"]))
    return "\n".join(lines)


def swarm_text(s: dict) -> str:
    lines = [f"swarm {s['runs_dir']} since={s['since']}" + (f" until={s['until']}" if s["until"] else "")]
    r = s["runs"]
    lines.append(f"runs: {r['count']}  segment_runs={r['segment_runs']}  watched={r['watched']}")
    if s["segments"]:
        lines.append(f"{'segment':<22}{'tries':>6}{'solves':>7}{'rate':>6}{'best':>8}{'median':>8}"
                     f"{'presses':>8}{'stall':>6}{'blackout':>9}{'loops':>6}")
        for seg, v in s["segments"].items():
            lines.append(f"{seg:<22}{v['attempts']:>6}{v['solves']:>7}{v['solve_rate']:>6.0%}"
                         f"{str(v['frames_best']):>8}{str(v['frames_median']):>8}{v['presses']:>8}"
                         f"{v['stall_rate']:>6.0%}{v['blackout_rate']:>9.0%}{v['loop_episodes']:>6}")
        for seg, v in s["segments"].items():
            if v["failing"]:
                lines.append(f"  {seg} failing: {', '.join(v['failing'])}")
    if s["top_stall_causes"]:
        lines.append("top stall causes:")
        for c in s["top_stall_causes"]:
            lines.append(f"  {c['count']}x {c['cause']} [{c['signature_key']}] e.g. {c['example']}")
    if s["top_rules"]:
        lines.append("top rules: " + ", ".join(f"{r['rule']}({r['presses']})" for r in s["top_rules"]))
    if s["new_checkpoints"]:
        lines.append("new checkpoints:")
        for c in s["new_checkpoints"]:
            lines.append(f"  {c['state']} map={c['map']} badges={c['badges']} party={c['party']} money={c['money']}")
    b = s["breaks"]
    lines.append("breaks:")
    lines.append(f"  invariants: {b['invariants']} errors={len(b['invariant_errors'])} warns={b['invariant_warns'] if isinstance(b['invariant_warns'], int) else len(b['invariant_warns'])}")
    for f in b["invariant_errors"]:
        lines.append(f"    ERROR {f['check']}/{f['kind']}: {f['message']}")
    if isinstance(b["invariant_warns"], list):
        for f in b["invariant_warns"]:
            lines.append(f"    WARN {f['check']}/{f['kind']}: {f['message']}")
    lines.append(f"  legality: {b['legality']}")
    for v in b["legality_violations"]:
        lines.append(f"    {v}")
    if b["crashed"]:
        lines.append(f"  crashed: {', '.join(b['crashed'])}")
    if b["no_decisions"]:
        lines.append(f"  no_decisions: {', '.join(b['no_decisions'])}")
    for e in b["loop_breaks"]:
        lines.append(f"  loop_break {e['run']} {e['kind']} presses={e['presses']} @{e['step']}")
    if s.get("skipped_rows"):
        lines.append(f"skipped_rows: {s['skipped_rows']}")
    return "\n".join(lines)


def diff_text(d: dict) -> str:
    lines = [f"diff {d['a']} vs {d['b']}"]
    for w in d["warnings"]:
        lines.append(f"not an apples-to-apples diff: {w['field']} differs ({w['a']} vs {w['b']})")
    dv = d["divergence"]
    if dv:
        lines.append(f"first divergence @step {dv['step']}: a={dv['a']} b={dv['b']}")
    elif d.get("prefix_only") is not None:
        lines.append(f"identical press stream; one is a prefix (shorter={d['prefix_only']})")
    else:
        lines.append("identical press stream")
    if d["goals"]:
        lines.append("per-goal timing:")
        for g, v in d["goals"].items():
            lines.append(f"  {g}: a={v['a']} b={v['b']} d_steps={v['delta_steps']}"
                         f" d_frames={v['delta_frames']} first={v['first']}")
    if d["segment"]:
        sg = d["segment"]
        lines.append(f"segment {sg['segment']}: d_frames={sg['delta_frames']} d_steps={sg['delta_steps']}")
    lines.append("event counts (a/b): " + ", ".join(
        f"{k} {v['a']}/{v['b']}" for k, v in d["event_counts"].items()))
    if d["rule_deltas"]:
        lines.append("rule share deltas:")
        for r in d["rule_deltas"]:
            lines.append(f"  {r['rule']}: {r['share_a']:.0%} -> {r['share_b']:.0%} ({r['delta']:+.0%})")
    lines.append(f"exp gained: a={d['exp']['a']} b={d['exp']['b']} delta={d['exp']['delta']}")
    lines.append(f"end: a={d['end']['a']['reason']} b={d['end']['b']['reason']}")
    return "\n".join(lines)


def _f(v, spec="{:.0%}", dash="-"):
    return dash if v is None else spec.format(v)


def _flags(r: dict) -> str:
    f = []
    if r["held"]:
        f.append(f"held({r['held']})")
    if r["solved"]:
        f.append("solved")
    if r["optimized"]:
        f.append("optimized")
    if r["stale"]:
        f.append("stale")
    if r["broken"]:
        f.append("BROKEN")
    if r["synthetic_only"]:
        f.append("synth?")
    return ",".join(f) or "-"


def segments_text(s: dict) -> str:
    lines = [f"segments scorecard  root={s['root']}" + (f"  suite={s['suite']}" if s.get("suite") else "")]
    lines.append(f"{'segment':<22}{'tries':>6}{'rate':>6}{'flags':<22}{'best':>8}{'par':>8}{'expected':>9}"
                 f"{'health':>7}{'blk%':>6}{'stl%':>6}{'loop%':>6}{'start':>10}{'share':>7}  cut_hints")
    for r in s["rows"]:
        hints = ";".join(f"{h['kind']}@{h['map']}#{h['step']}" for h in r["cut_hints"]) or "-"
        lines.append(f"{r['segment']:<22}{r['tries']:>6}{_f(r['rate']):>6}{_flags(r):<22}"
                     f"{_f(r['best'], '{:.0f}'):>8}{_f(r['par'], '{:.0f}'):>8}{_f(r['expected'], '{:.0f}'):>9}"
                     f"{_f(r['health'], '{:.0%}'):>7}{_f(r['blackout_rate']):>6}{_f(r['stall_rate']):>6}"
                     f"{_f(r['loop_rate']):>6}{r['start'][-9:]:>10}{r['share']:>6.0%}  {hints}")
    sh = s["shares"]
    lines.append(f"shares: unsolved={sh.get('unsolved', 0):.0%} frontier={sh.get('frontier', 0):.0%} "
                 f"polish={sh.get('polish', 0):.0%}" + (f" rejoin={sh.get('rejoin', 0):.0%}" if "rejoin" in sh else ""))
    lines.append(f"frontier: {s['frontier'] or '-'}  health={_f(s['frontier_health'], '{:.2f}')} "
                 f"explore_rate={_f(s['explore_rate'], '{:.2f}')}")
    if s["rejoin_candidates"]:
        lines.append("rejoin candidates: " + ", ".join(s["rejoin_candidates"]))
    if s["broken"]:
        lines.append("BROKEN segments present (exit 1)")
    return "\n".join(lines)


def replay_text(r: dict) -> str:
    lines = [f"replay {r['run']} steps={r['steps']}: {r['status']}"]
    if r.get("warning"):
        lines.append(f"warning: {r['warning']}")
    if r.get("reason"):
        lines.append(f"reason: {r['reason']}")
    dv = r.get("divergence")
    if dv:
        lines.append(f"divergence @step {dv['step']} field={dv['field']}"
                     f" agreed_steps={dv['agreed_steps']}")
        lines.append(f"  a={dv['a']}  b={dv['b']}  rules={dv['rule_a']}/{dv['rule_b']}")
    if r.get("command"):
        lines.append("command: " + " ".join(r["command"]))
    return "\n".join(lines)
