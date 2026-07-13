"""DecisionRecord exporter: replay recorded games into an ML-ready dataset.

Every game the lab runs stores a `(seed, action log)` GameRecord
(results/records.jsonl). This tool replays those records and captures, at
every decision point, the **canonical symbolic state** (the PlayerView the
acting bot saw), the legal action menu, the chosen action, and the game
outcome — one JSON row per decision in results/decisions.jsonl.

Design (see README): symbolic state first, tensors derived later. Static
map topology is referenced by `state.map_name` (operations/data/maps/) and
never duplicated per row; everything dynamic lives in `state`. Tensor
builders (v1, v2, ...) regenerate from these rows — or, since the records
themselves replay deterministically, from scratch — so feature schemas can
evolve without invalidating collected data. The engine stays ML-agnostic:
this file only *observes* replays.

    uv run python operations/research/decision_export.py            # all records
    uv run python operations/research/decision_export.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))

from ticket_to_ride.engine.game import Game                              # noqa: E402
from ticket_to_ride.engine.player import Player                         # noqa: E402
from ticket_to_ride.engine.replay import (                              # noqa: E402
    GameRecord, ScriptedBot, action_to_dict,
)
from ticket_to_ride.engine.state.game_context import GameContext        # noqa: E402

RESULTS_DIR = REPO / "operations" / "research" / "results"
RECORDS_FILE = RESULTS_DIR / "records.jsonl"
DECISIONS_FILE = RESULTS_DIR / "decisions.jsonl"

#: Bump when the symbolic state layout changes so downstream tensor
#: builders can dispatch on it.
STATE_SCHEMA_VERSION = 1


class _SilentLogger:
    def record_turn(self, *args, **kwargs):
        return None


class _ObservingBot(ScriptedBot):
    """Feeds the recorded actions back while capturing every decision."""

    def __init__(self, script, sink, player_id):
        super().__init__(script)
        self._sink = sink
        self._player_id = player_id

    def act(self, view, legal_actions):
        action = super().act(view, legal_actions)
        self._sink.append((self._player_id, view, list(legal_actions), action))
        return action


def symbolic_state(view) -> dict:
    """The canonical symbolic state: everything the acting seat could see.

    Static topology is referenced via map_name rather than embedded —
    regenerate node/edge structure from operations/data/maps/<map>.csv.
    """
    return {
        "map_name": view.map_name,
        "player_count": view.player_count,
        "turn_number": view.turn_number,
        "score": view.score,
        "trains_remaining": view.trains_remaining,
        "hand": dict(view.hand),
        "tickets": [
            {"city1": t.city1, "city2": t.city2, "value": t.value,
             "completed": t.is_completed, "impossible": t.is_impossible}
            for t in view.tickets
        ],
        "market": list(view.face_up_cards),
        "discard": dict(view.discard_pile),
        "train_cards_in_deck": view.train_cards_in_deck,
        "tickets_in_deck": view.tickets_in_deck,
        "claimed_by": dict(view.claimed_by),
        "opponents": [
            {"player_id": o.player_id, "exposed": dict(o.exposed_hand),
             "hand_count": o.num_cards_in_hand, "trains": o.remaining_trains,
             "score": o.score, "ticket_count": o.destination_ticket_count}
            for o in view.opponents
        ],
        "ticket_offer": [
            {"city1": t.city1, "city2": t.city2, "value": t.value}
            for t in (view.ticket_offer or [])
        ] or None,
    }


def decisions_from_record(record: GameRecord, meta: dict) -> list:
    """Replay one recorded game and emit a DecisionRecord per decision."""
    sink = []
    scripts = {
        player_id: [a for owner, a in record.actions if owner == player_id]
        for player_id in record.player_ids
    }
    players = [
        Player(player_id, _ObservingBot(scripts[player_id], sink, player_id),
               player_id, "gray")
        for player_id in record.player_ids
    ]
    context = GameContext(record.player_ids, map_name=record.map_name, seed=record.seed)
    Game(context, players, _SilentLogger(), 0).play()
    scores = context.scores

    rows = []
    for index, (player_id, view, legal, action) in enumerate(sink):
        others = [s for p, s in scores.items() if p != player_id]
        rows.append({
            **meta,
            "state_schema_version": STATE_SCHEMA_VERSION,
            "decision_index": index,
            "player": player_id,
            "decision": view.decision,
            "state": symbolic_state(view),
            "legal_actions": [action_to_dict(a) for a in legal],
            "chosen": action_to_dict(action),
            "outcome": {
                "final_score": scores[player_id],
                "margin": scores[player_id] - max(others) if others else 0,
                "won": all(scores[player_id] > s for s in others),
            },
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=RECORDS_FILE)
    parser.add_argument("--out", type=Path, default=DECISIONS_FILE)
    parser.add_argument("--limit", type=int, default=None, help="max games to export")
    args = parser.parse_args()

    if not args.records.exists():
        raise SystemExit(f"No records at {args.records} — run bot_lab.py first.")

    started = time.perf_counter()
    games = decisions = 0
    with args.records.open() as records, args.out.open("w") as out:
        for line in records:
            if not line.strip():
                continue
            if args.limit is not None and games >= args.limit:
                break
            row = json.loads(line)
            record = GameRecord.from_dict(row["record"])
            meta = {"tag": row.get("tag"), "opponent": row.get("opponent"),
                    "seed": row.get("seed"), "fable_first": row.get("fable_first")}
            for decision in decisions_from_record(record, meta):
                out.write(json.dumps(decision) + "\n")
                decisions += 1
            games += 1

    print(f"exported {decisions} decisions from {games} games "
          f"to {args.out} in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
