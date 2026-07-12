# Bot research lab

Tools for studying bot play. `bot_lab.py` is the engine + CLI (seeded duel
tournaments, per-game score decomposition, JSONL accumulation);
`bot_lab_dashboard.py` is the marimo dashboard over the same results file,
and can launch runs itself.

```
uv run python operations/research/bot_lab.py --games 40
uv run python operations/research/bot_lab.py --sweep _ENDGAME_TURNS=6,8,10 --opponents qualifier
uv run --extra notebooks marimo edit operations/research/bot_lab_dashboard.py
```

Results land in `results/games.jsonl` (gitignored). `--fresh` starts over.

`map_eval.py` implements the two map-generation loops: Loop 1 structural
descriptors ("does it look like a TTR map?") and a Loop 2 QualifierBot
mirror-match gauntlet ("does it play balanced?" — self-play isolates the
map signal). Profiles archive to `results/map_profiles.jsonl`;
`map_metrics_dashboard.py` is the marimo view. Calibration from the human
maps (40-game gauntlets): ticket value ≈ 1.0 points/train on BOTH maps,
claim entropy ≈ 0.9, ticket completion 0.78-0.83, seat balance ≈ 0.5 —
those bands are the generator's acceptance targets. The GPU-side GNN work
is planned in docs/superpowers/plans/2026-07-12-gnn-policy-gpu.md.

## Telemetry design (layered, bot-agnostic)

**Layer 1 — engine facts** (implemented): everything observable from the
finished game with zero bot cooperation: outcome, margin, score decomposition
(routes / completed tickets / impossible + pending penalties / longest path),
ticket counts, trains left, turns, action mix (blind vs face-up vs locomotive
draws, claims, ticket draws), the full heuristic configuration of the run.
Because every game records `(seed, action log)`, all of layer 1 is
reconstructible retroactively at any decision point via `engine.replay`.

**Layer 2 — external evaluation** (next): don't ask what the bot was
thinking; ask what a strong external evaluator thinks was available at each
decision, then compare. Replay each recorded decision point, score every
legal action with independent evaluator lenses (ticket completion, route
points, blocking, card economy, endgame), and report per-bot agreement rates
per lens. Note this is *relative* agreement, not ground-truth regret — the
evaluators are themselves heuristics. Derived per-decision facts worth
logging: claim delay after a planned route becomes affordable, ticket ROI at
keep time, whether an endgame trigger happened ahead or behind.

**Layer 2.5 — counterfactual rollout** (the rigorous version): the seeded
replay makes true action-value estimates possible without ML — branch a
recorded decision, substitute an alternative action, roll the game forward
under the same policies across several continuation seeds, and measure the
outcome delta. Expensive (one full game per branch per seed) but it turns
"the evaluator disagrees" into "this choice cost ~N points."

**Layer 2 implemented: the DecisionRecord dataset.** `decision_export.py`
replays the GameRecords the lab stores (results/records.jsonl, one
`(seed, action log)` per game) and emits one row per decision to
results/decisions.jsonl: the canonical **symbolic state** (the PlayerView
the acting seat saw — hand, tickets, market, discard, claimed_by,
opponents, deck counts, ticket offer), the legal action menu, the chosen
action, and the outcome (final score / margin / won). Design rules:
symbolic state first, tensors derived by versioned TensorBuilders later
(`state_schema_version` dispatches); static map topology is referenced by
`state.map_name` (operations/data/maps/<map>.csv now also carries
Locomotives/Tunnel columns), never duplicated per row; the engine stays
ML-agnostic — the exporter only observes replays, so old records can be
re-exported forever as feature schemas evolve.

**Layer 3 — optional introspection**: bots MAY expose
`explain(view, legal_actions) -> dict` (mode, planned routes, card needs,
action scores). The harness records it when present and never requires it.
