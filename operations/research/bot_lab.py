"""Bot research lab: seeded duel tournaments with full score decomposition.

Runs FableBestBot (optionally with overridden heuristics) against sibling
bots, prints a terminal readout, and appends one JSON row per game to a results
file. The marimo dashboard (bot_lab_dashboard.py, same directory) reads and
visualizes everything accumulated there — and can launch runs itself.

Examples
--------
    uv run python operations/research/bot_lab.py --games 40
    uv run python operations/research/bot_lab.py --games 40 \
        --tag loco-0.5 --set _LOCO_OPTION_COST=0.5
    uv run python operations/research/bot_lab.py --games 60 \
        --opponents qualifier --sweep _ENDGAME_TURNS=6,8,10

`--set`/`--sweep` subclass FableBestBot in memory; the bot file itself is
never modified. Results accumulate in operations/research/results/games.jsonl
(gitignored).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))

from external.bots.example_bot import ExampleBot            # noqa: E402
from external.bots.fable_best_bot import FableBestBot       # noqa: E402
from external.bots.qualifier_bot import QualifierBot        # noqa: E402
from external.bots.random_bot import RandomBot               # noqa: E402
from notebook_harness.game_runner import initialize_game     # noqa: E402
from ticket_to_ride.engine.actions import (                  # noqa: E402
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets,
)
from ticket_to_ride.engine.replay import record_of            # noqa: E402

OPPONENTS = {"qualifier": QualifierBot, "example": ExampleBot, "random": RandomBot}
RESULTS_DIR = REPO / "operations" / "research" / "results"
RESULTS_FILE = RESULTS_DIR / "games.jsonl"
CLAIMS_FILE = RESULTS_DIR / "claims.jsonl"
RECORDS_FILE = RESULTS_DIR / "records.jsonl"


def tunables(bot_class) -> dict:
    """Every numeric heuristic constant on the bot (its _UPPER_CASE attrs)."""
    values = {}
    for name in dir(bot_class):
        if not name.startswith("_") or not name.lstrip("_").isupper():
            continue
        value = getattr(bot_class, name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values[name] = value
    return values


def build_variant(overrides: dict):
    if not overrides:
        return FableBestBot
    return type("TunedFableBestBot", (FableBestBot,), dict(overrides))


def decompose(player, scores, map_graph) -> dict:
    tickets = player.get_tickets()
    completed = [t for t in tickets if t.is_completed]
    impossible = [t for t in tickets if t.is_impossible]
    pending = [t for t in tickets if not t.is_completed and not t.is_impossible]
    claimed = map_graph.get_claimed_routes(player.player_id)
    return {
        "score": scores[player.player_id],
        "route_pts": scores[player.player_id]
        - sum(t.value for t in completed)
        + sum(t.value for t in impossible)
        + sum(t.value for t in pending)
        - (10 if player.has_longest_path else 0),
        "tickets_completed_pts": sum(t.value for t in completed),
        "tickets_impossible_pts": sum(t.value for t in impossible),
        "tickets_pending_pts": sum(t.value for t in pending),
        "longest_path": player.has_longest_path,
        "tickets_kept": len(tickets),
        "tickets_completed_n": len(completed),
        "trains_left": player.trains_remaining,
        "claims": len(claimed),
        "avg_claim_len": round(
            sum(r.length for r in claimed) / len(claimed), 2
        ) if claimed else 0.0,
    }


def action_mix(action_log, player_id) -> dict:
    counts = Counter()
    for owner, action in action_log:
        if owner != player_id:
            continue
        if isinstance(action, DrawBlind):
            counts["blind_draws"] += 1
        elif isinstance(action, DrawFaceUp):
            counts["loco_takes" if action.card == "L" else "faceup_draws"] += 1
        elif isinstance(action, ClaimRoute):
            counts["claim_actions"] += 1
        elif isinstance(action, DrawTickets):
            counts["ticket_draws"] += 1
    return dict(counts)


def claim_events(game, tag, opponent_name, seed):
    """One row per claimed route: the observable trace of hidden tickets.

    `critical_for` lists the owner's completed tickets that would disconnect
    without this route — the ticket_route_dependency signal for intent
    inference and choke-point discovery (see README layer-2 stats).
    """
    context = game.game.context
    scores = context.scores
    order = {}
    for owner, action in context.action_log:
        if isinstance(action, ClaimRoute):
            order[action.route_id] = len(order) + 1
    total_claims = max(1, len(order))

    events = []
    for player in game.players:
        claimed = context.get_map().get_claimed_routes(player.player_id)
        completed = [t for t in player.get_tickets() if t.is_completed]

        def connects(ticket, routes):
            parent = {}
            def find(x):
                parent.setdefault(x, x)
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            for r in routes:
                ra, rb = find(r.city1), find(r.city2)
                if ra != rb:
                    parent[ra] = rb
            return find(ticket.city1) == find(ticket.city2)

        opponent_ids = [p.player_id for p in game.players if p is not player]
        won = all(scores[player.player_id] > scores[o] for o in opponent_ids)
        for route in claimed:
            others = [r for r in claimed if r is not route]
            events.append({
                "tag": tag, "opponent": opponent_name, "seed": seed,
                "player": player.player_id,
                "role": "fable" if player.name.startswith("Fable") else "opponent",
                "won": won, "final_score": scores[player.player_id],
                "route_id": route.route_id, "city1": route.city1, "city2": route.city2,
                "length": route.length, "color": route.color,
                "claim_order": order.get(route.route_id, 0),
                "turn_bucket": ["early", "mid", "late"][
                    min(2, 3 * (order.get(route.route_id, 1) - 1) // total_claims)],
                "tickets": [f"{t.city1}→{t.city2}" for t in player.get_tickets()],
                "completed_tickets": [f"{t.city1}→{t.city2}" for t in completed],
                "critical_for": [
                    f"{t.city1}→{t.city2}" for t in completed if not connects(t, others)
                ],
            })
    return events


def run_matchup(tag, variant, opponent_name, games, seed_base):
    opponent_class = OPPONENTS[opponent_name]
    rows = []
    events = []
    records = []
    for i in range(games):
        fable_first = i % 2 == 0
        seats = [variant(), opponent_class()] if fable_first else [opponent_class(), variant()]
        game = initialize_game(seats, seed=seed_base + i)
        game.play()
        scores = game.game.context.scores
        fable_id = "bot_0" if fable_first else "bot_1"
        opp_id = "bot_1" if fable_first else "bot_0"
        fable_player = game.players[0] if fable_first else game.players[1]
        map_graph = game.game.context.get_map()

        fable = decompose(fable_player, scores, map_graph)
        fable.update(action_mix(game.game.context.action_log, fable_id))
        events.extend(claim_events(game, tag, opponent_name, seed_base + i))
        records.append({
            "tag": tag, "opponent": opponent_name, "seed": seed_base + i,
            "fable_first": fable_first,
            "record": record_of(game.game).to_dict(),
        })
        rows.append({
            "tag": tag,
            "opponent": opponent_name,
            "seed": seed_base + i,
            "fable_first": fable_first,
            "won": scores[fable_id] > scores[opp_id],
            "margin": scores[fable_id] - scores[opp_id],
            "opp_score": scores[opp_id],
            "turns": game.snapshot_count(),
            "fable": fable,
            "config": tunables(variant),
        })
    return rows, events, records


def readout(rows) -> None:
    """Terminal summary: one block per (tag, opponent)."""
    by_key = {}
    for row in rows:
        by_key.setdefault((row["tag"], row["opponent"]), []).append(row)

    for (tag, opponent), games in sorted(by_key.items()):
        margins = [g["margin"] for g in games]
        wins = sum(g["won"] for g in games)
        f = lambda key: statistics.mean(g["fable"].get(key, 0) for g in games)  # noqa: E731
        print(f"\n[{tag}] vs {opponent} — {wins}/{len(games)} "
              f"({100 * wins / len(games):.0f}%)  "
              f"margin {statistics.mean(margins):+.1f} "
              f"(sd {statistics.pstdev(margins):.0f})")
        print(f"  score {f('score'):6.1f} = routes {f('route_pts'):5.1f} "
              f"+ tickets {f('tickets_completed_pts'):5.1f} "
              f"- impossible {f('tickets_impossible_pts'):4.1f} "
              f"- pending {f('tickets_pending_pts'):4.1f} "
              f"+ LP {10 * statistics.mean(g['fable']['longest_path'] for g in games):4.1f}")
        print(f"  tickets kept {f('tickets_kept'):.1f} (completed {f('tickets_completed_n'):.1f})"
              f"  trains left {f('trains_left'):.1f}  claims {f('claims'):.1f}"
              f" (len {f('avg_claim_len'):.2f})  loco takes {f('loco_takes'):.1f}")
        worst = sorted(games, key=lambda g: g["margin"])[:3]
        for g in worst:
            fb = g["fable"]
            print(f"    worst: seed {g['seed']} margin {g['margin']:+d} "
                  f"(imp -{fb['tickets_impossible_pts']} pend -{fb['tickets_pending_pts']} "
                  f"trains {fb['trains_left']})")


def load_all_rows() -> list:
    if not RESULTS_FILE.exists():
        return []
    return [json.loads(line) for line in RESULTS_FILE.read_text().splitlines() if line.strip()]


def append_rows(rows) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_FILE.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")




def parse_overrides(pairs):
    overrides = {}
    for pair in pairs or []:
        key, _, raw = pair.partition("=")
        overrides[key.strip()] = float(raw) if "." in raw else int(raw)
    return overrides


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=40, help="games per opponent")
    parser.add_argument("--opponents", default="qualifier,example",
                        help=f"comma list from {sorted(OPPONENTS)}")
    parser.add_argument("--seed-base", type=int, default=9000)
    parser.add_argument("--tag", default="baseline", help="config label for this run")
    parser.add_argument("--set", dest="sets", action="append", metavar="KEY=VALUE",
                        help="override a FableBestBot heuristic (repeatable)")
    parser.add_argument("--sweep", metavar="KEY=V1,V2,...",
                        help="run one tagged config per value")
    parser.add_argument("--fresh", action="store_true",
                        help="discard previously accumulated results first")
    args = parser.parse_args()

    if args.fresh:
        for stale in (RESULTS_FILE, CLAIMS_FILE, RECORDS_FILE):
            if stale.exists():
                stale.unlink()

    configs = []
    base_overrides = parse_overrides(args.sets)
    if args.sweep:
        key, _, raw = args.sweep.partition("=")
        for value in raw.split(","):
            v = float(value) if "." in value else int(value)
            configs.append((f"{args.tag}:{key.lstrip('_')}={v}",
                            {**base_overrides, key.strip(): v}))
    else:
        configs.append((args.tag, base_overrides))

    started = time.perf_counter()
    new_rows = []
    new_events = []
    new_records = []
    for tag, overrides in configs:
        variant = build_variant(overrides)
        for opponent in args.opponents.split(","):
            rows, events, records = run_matchup(tag, variant, opponent.strip(),
                                                args.games, args.seed_base)
            new_rows.extend(rows)
            new_events.extend(events)
            new_records.extend(records)

    readout(new_rows)
    append_rows(new_rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with CLAIMS_FILE.open("a") as handle:
        for event in new_events:
            handle.write(json.dumps(event) + "\n")
    with RECORDS_FILE.open("a") as handle:
        for record_row in new_records:
            handle.write(json.dumps(record_row) + "\n")
    total = len(load_all_rows())
    print(f"\n({len(new_rows)} games in {time.perf_counter() - started:.1f}s; "
          f"{total} accumulated in {RESULTS_FILE})")


if __name__ == "__main__":
    main()
