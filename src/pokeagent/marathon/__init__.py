"""Marathon watch: a stall detector for single long runs (tools/marathon_watch.py).

tools/swarm_watch.py's ProgressWatch frees swarm slots when an agent is hung or in a tight loop;
a single marathon run trickles new tiles and XP forever and so never trips it. The rules here catch
what it missed: no new campaign goal for thousands of presses while the run looks alive.

reader.RunView parses one run dir incrementally (read-only), rules.py judges it, bundle.py writes
the post-mortem JSON and actions.py asks the run to save/stop over its control API. Nothing here
ever touches a process: files only.
"""
