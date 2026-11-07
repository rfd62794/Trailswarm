Synthetic review fixtures - the layout and scenarios the review tests expect. NOT committed:
the root .gitignore rule "runs/" also matches tests/fixtures/review/runs/, so this directory holds
only this README. No generator exists either; the tests that read runs/ (test_review_run,
test_review_swarm, test_review_replay, test_review_diff, test_cli_review) fail on a clean checkout
until the runs/ tree is restored. Every run in it is hand-written test data (meta.json carries
"synthetic": true), NOT a copy of a real run. Layout mirrors runs/: explore-YYYYMMDD-HHMMSS-pid
dirs with distinct timestamps (2026-11-07 15:00..15:40) plus shared milestones.json, battles.jsonl,
stalls/, checkpoints/ and segments/inputs/ so the review tools can be exercised read-only.

Scenarios the tests assert on:

run_ok          explore-20261107-150000-1001  solved seg:gyarados run: goal_frames, a 35->36->35
                                            map bounce, a 35->37 warp, a trainer win + a wild win,
                                            heal and buy blocks, level gains, one claude press.
run_ok_b        explore-20261107-150100-1006  same start; diverges at press 7 (LEFT), seed differs.
run_stall       explore-20261107-151000-1002  seg:gyarados; dossier + a 40-row blocked loop.
run_alreadyout  explore-20261107-152000-1003  seg:to_bill; a 12-row "already out" text loop, solved.
run_blackout    explore-20261107-153000-1004  seg:gyarados; battles.jsonl has its blackout record.
run_crash       explore-20261107-154000-1005  meta.json + error.txt only; no decisions.jsonl.
