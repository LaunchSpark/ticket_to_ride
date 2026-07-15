"""Classic-map data pump for XG Bot research.

This runner keeps generated games in the normal replay system when the backend
is reachable, while also writing ML-ready DecisionRecord rows immediately. It
avoids the replay/export bottleneck for training, but still leaves a durable
game trace for inspection.

Examples
--------
    uv run --extra notebooks python operations/research/xg_data_pump.py --games 25
    uv run --extra notebooks python operations/research/xg_data_pump.py --forever --train-every-decisions 10000
    uv run --extra notebooks python operations/research/xg_data_pump.py --games 1 --no-db
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))
sys.path.insert(0, str(REPO / "operations" / "research"))

from decision_export import STATE_SCHEMA_VERSION, symbolic_state  # noqa: E402
from external.clients.bot_api.loader import BotDescriptor, BotLoader  # noqa: E402
from external.ml import xgb_features  # noqa: E402
from ticket_to_ride.engine.game import Game  # noqa: E402
from ticket_to_ride.engine.player import Player  # noqa: E402
from ticket_to_ride.engine.replay import action_to_dict, record_of  # noqa: E402
from ticket_to_ride.engine.state.game_context import GameContext  # noqa: E402
from ticket_to_ride.logging.game_logger import GameLogger, LoggerClientError  # noqa: E402

CLASSIC_MAP = "classic"
RESULTS_DIR = REPO / "operations" / "research" / "results"
RECORDS_FILE = RESULTS_DIR / "records.jsonl"
DECISIONS_FILE = RESULTS_DIR / "decisions.jsonl"
FEATURE_ROWS_FILE = RESULTS_DIR / "xg_pump_feature_rows.jsonl"
PUMP_GAMES_FILE = RESULTS_DIR / "xg_pump_games.jsonl"
PLAYER_COLORS = ["red", "blue", "green", "yellow", "black"]
CapturedDecision = tuple[str, str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SeatSpec:
    seat_id: str
    bot_id: str
    bot_name: str
    bot: Any


class RecordingBot:
    """Proxy that records the exact legal decision menu seen by a bot."""

    def __init__(
        self,
        inner: Any,
        seat_id: str,
        sink: list[CapturedDecision],
        *,
        capture_decisions: bool,
    ) -> None:
        self.inner = inner
        self.seat_id = seat_id
        self.sink = sink
        self.capture_decisions = capture_decisions

    def set_player(self, player: Player) -> None:
        self.player = player
        if callable(getattr(self.inner, "set_player", None)):
            self.inner.set_player(player)

    def begin_turn(self) -> None:
        begin_turn = getattr(self.inner, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()

    def end_turn(self, completed: bool) -> None:
        end_turn = getattr(self.inner, "end_turn", None)
        if callable(end_turn):
            end_turn(completed)

    def act(self, view: Any, legal_actions: list[Any]) -> Any:
        action = self.inner.act(view, legal_actions)
        if action not in legal_actions:
            action = legal_actions[0]
        if self.capture_decisions:
            self.sink.append((
                self.seat_id,
                view.decision,
                symbolic_state(view),
                [action_to_dict(legal_action) for legal_action in legal_actions],
                action_to_dict(action),
            ))
        return action


class NullLogger:
    def record_turn(self, *_args, **_kwargs) -> None:
        return None


def load_bot_pool(*, include_xg_bot: bool = False) -> tuple[BotDescriptor, list[BotDescriptor]]:
    descriptors = BotLoader().load_bots()
    qualifier = descriptors["qualifier_bot"]
    alternatives = [
        descriptor
        for bot_id, descriptor in sorted(descriptors.items())
        if bot_id != "qualifier_bot" and (include_xg_bot or bot_id != "xg_bot")
    ]
    if not alternatives:
        raise RuntimeError("No non-Qualifier bots are available for mixed-seat generation.")
    return qualifier, alternatives


def sample_seats(
    rng: random.Random,
    *,
    player_count: int,
    qualifier: BotDescriptor,
    alternatives: list[BotDescriptor],
    non_qualifier_probability: float,
) -> list[SeatSpec]:
    seats = []
    for index in range(player_count):
        descriptor = (
            rng.choice(alternatives)
            if rng.random() < non_qualifier_probability
            else qualifier
        )
        seats.append(
            SeatSpec(
                seat_id=f"bot_{index}",
                bot_id=descriptor.bot_id,
                bot_name=descriptor.metadata.name,
                bot=descriptor.bot_class(),
            )
        )
    return seats


def run_generated_game(
    *,
    seed: int,
    qualifier: BotDescriptor,
    alternatives: list[BotDescriptor],
    min_players: int,
    max_players: int,
    non_qualifier_probability: float,
    require_db: bool,
    no_db: bool,
    tag: str,
) -> dict[str, Any]:
    rng = random.Random(seed)
    player_count = rng.randint(min_players, max_players)
    seats = sample_seats(
        rng,
        player_count=player_count,
        qualifier=qualifier,
        alternatives=alternatives,
        non_qualifier_probability=non_qualifier_probability,
    )
    decisions: list[CapturedDecision] = []
    players = [
        Player(
            seat.seat_id,
            RecordingBot(
                seat.bot,
                seat.seat_id,
                decisions,
                capture_decisions=seat.bot_id == "qualifier_bot",
            ),
            f"{seat.bot_name} [{seat.seat_id}]",
            PLAYER_COLORS[index % len(PLAYER_COLORS)],
        )
        for index, seat in enumerate(seats)
    ]

    logger, replay_match_id = build_logger(
        players,
        match_name=f"xg-data-pump seed {seed}",
        require_db=require_db,
        no_db=no_db,
    )
    context = GameContext([seat.seat_id for seat in seats], map_name=CLASSIC_MAP, seed=seed)
    game = Game(context, players, logger, 0)
    if replay_match_id is not None:
        logger.start_round(0)
    game.play()
    if replay_match_id is not None:
        logger.finalize_match()

    scores = context.scores
    seat_bots = {
        seat.seat_id: {"bot_id": seat.bot_id, "name": seat.bot_name}
        for seat in seats
    }
    meta = {
        "tag": tag,
        "source": "xg_data_pump",
        "seed": seed,
        "map": CLASSIC_MAP,
        "player_count": player_count,
        "seat_bots": seat_bots,
        "replay_match_id": replay_match_id,
        "captured_bot_id": "qualifier_bot",
    }
    decision_rows = decision_rows_from_capture(decisions, scores=scores, meta=meta)
    record_row = {
        **meta,
        "record": record_of(game).to_dict(),
    }
    summary_row = {
        **meta,
        "scores": scores,
        "winner": max(scores, key=scores.get),
        "decision_count": len(decision_rows),
        "action_count": len(context.action_log),
    }
    return {
        "record": record_row,
        "decisions": decision_rows,
        "summary": summary_row,
    }


def build_logger(
    players: list[Player],
    *,
    match_name: str,
    require_db: bool,
    no_db: bool,
) -> tuple[Any, str | None]:
    if no_db:
        return NullLogger(), None
    logger = GameLogger(players)
    try:
        match_id = logger.start_match(match_name)
    except (LoggerClientError, OSError, ValueError) as exc:
        if require_db:
            raise RuntimeError(f"Unable to create DB replay match: {exc}") from exc
        print(f"[xg-data-pump] DB logger unavailable, writing research JSONL only: {exc}")
        return NullLogger(), None
    return logger, match_id


def decision_rows_from_capture(
    captured: list[CapturedDecision],
    *,
    scores: dict[str, int],
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for index, (player_id, decision, state, legal_actions, chosen) in enumerate(captured):
        others = [score for other_id, score in scores.items() if other_id != player_id]
        rows.append({
            **meta,
            "state_schema_version": STATE_SCHEMA_VERSION,
            "decision_index": index,
            "player": player_id,
            "decision": decision,
            "state": state,
            "legal_actions": legal_actions,
            "chosen": chosen,
            "outcome": {
                "final_score": scores[player_id],
                "margin": scores[player_id] - max(others) if others else 0,
                "won": all(scores[player_id] > score for score in others),
            },
        })
    return rows


def cached_rank_groups_from_decisions(
    decisions: list[dict[str, Any]],
    *,
    schema: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Precompute dense state-action feature groups for faster checkpoint training."""
    feature_schema = list(schema or xgb_features.feature_names())
    groups: list[dict[str, Any]] = []
    for row in decisions:
        legal_actions = list(row.get("legal_actions") or [])
        chosen_index = xgb_features.chosen_action_index(row)
        if chosen_index is None or not legal_actions:
            continue
        action_rows = xgb_features.build_action_feature_rows(row, legal_actions)
        if chosen_index >= len(action_rows):
            continue
        labels = [1 if index == chosen_index else 0 for index in range(len(action_rows))]
        state = row.get("state") or {}
        groups.append({
            "feature_schema_version": 1,
            "feature_count": len(feature_schema),
            "features": [
                [float(feature_row.get(name, 0.0)) for name in feature_schema]
                for feature_row in action_rows
            ],
            "labels": labels,
            "chosen_index": chosen_index,
            "group_size": len(action_rows),
            "decision": str(row.get("decision") or state.get("decision") or "turn"),
            "map": str(state.get("map_name") or row.get("map") or CLASSIC_MAP),
            "player": row.get("player"),
            "decision_index": row.get("decision_index"),
            "seed": row.get("seed"),
        })
    return groups


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def train_if_requested(args: argparse.Namespace, decisions_since_train: int) -> bool:
    if not args.train_every_decisions or decisions_since_train < args.train_every_decisions:
        return False
    try:
        import train_xg_bot
    except Exception as exc:
        print(f"[xg-data-pump] training skipped: {exc}")
        return False
    cached_groups = train_xg_bot.load_cached_groups(args.feature_rows_out, limit=args.train_limit or None)
    try:
        model, schema, report = train_xg_bot.train_ranker_from_cached_groups(
            cached_groups,
            n_estimators=args.train_estimators,
            max_depth=args.train_max_depth,
            learning_rate=args.train_learning_rate,
        )
    except SystemExit as exc:
        print(f"[xg-data-pump] training skipped: {exc}")
        return False
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(args.model_out))
    train_xg_bot.write_feature_schema(args.features_out, schema=schema, model_path=args.model_out, report=report)
    print(
        f"[xg-data-pump] trained after {decisions_since_train} new Qualifier decisions: "
        f"top1={report['top1_accuracy']:.3f}, mrr={report['mean_reciprocal_rank']:.3f}"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=25, help="number of games to generate")
    parser.add_argument("--forever", action="store_true", help="keep generating until interrupted")
    parser.add_argument("--seed-base", type=int, default=None, help="first seed; random when omitted")
    parser.add_argument("--min-players", type=int, default=2)
    parser.add_argument("--max-players", type=int, default=5)
    parser.add_argument("--non-qualifier-probability", type=float, default=0.25)
    parser.add_argument("--include-xg-bot", action="store_true", help="allow XG Bot as a non-Qualifier sampled seat")
    parser.add_argument("--tag", default="xg-pump")
    parser.add_argument("--require-db", action="store_true", help="fail if the normal match DB/logger is unavailable")
    parser.add_argument("--no-db", action="store_true", help="skip normal DB logging; useful for local smoke tests")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to pause between games")
    parser.add_argument("--records-out", type=Path, default=RECORDS_FILE)
    parser.add_argument("--decisions-out", type=Path, default=DECISIONS_FILE)
    parser.add_argument("--feature-rows-out", type=Path, default=FEATURE_ROWS_FILE)
    parser.add_argument("--summaries-out", type=Path, default=PUMP_GAMES_FILE)
    parser.add_argument("--train-every-decisions", type=int, default=0, help="train XG Bot after every N captured Qualifier decisions")
    parser.add_argument("--train-limit", type=int, default=0, help="max cached decision groups for periodic training; 0 = all")
    parser.add_argument("--train-estimators", type=int, default=200)
    parser.add_argument("--train-max-depth", type=int, default=4)
    parser.add_argument("--train-learning-rate", type=float, default=0.05)
    parser.add_argument("--model-out", type=Path, default=RESULTS_DIR / "xg_bot_ranker.json")
    parser.add_argument("--features-out", type=Path, default=RESULTS_DIR / "xg_bot_features.json")
    args = parser.parse_args()

    if args.min_players < 2 or args.max_players > 5 or args.min_players > args.max_players:
        raise SystemExit("Player count range must be between 2 and 5.")
    if not 0.0 <= args.non_qualifier_probability <= 1.0:
        raise SystemExit("--non-qualifier-probability must be between 0 and 1.")
    if args.require_db and args.no_db:
        raise SystemExit("--require-db and --no-db cannot both be set.")

    qualifier, alternatives = load_bot_pool(include_xg_bot=args.include_xg_bot)
    seed_base = args.seed_base if args.seed_base is not None else random.randrange(2**31)
    games_completed = 0
    decisions_since_train = 0
    started = time.perf_counter()
    feature_schema = xgb_features.feature_names()

    try:
        while args.forever or games_completed < args.games:
            seed = seed_base + games_completed
            result = run_generated_game(
                seed=seed,
                qualifier=qualifier,
                alternatives=alternatives,
                min_players=args.min_players,
                max_players=args.max_players,
                non_qualifier_probability=args.non_qualifier_probability,
                require_db=args.require_db,
                no_db=args.no_db,
                tag=args.tag,
            )
            cached_groups = cached_rank_groups_from_decisions(result["decisions"], schema=feature_schema)
            append_jsonl(args.records_out, [result["record"]])
            append_jsonl(args.decisions_out, result["decisions"])
            append_jsonl(args.feature_rows_out, cached_groups)
            append_jsonl(args.summaries_out, [result["summary"]])
            games_completed += 1
            decisions_since_train += len(cached_groups)
            summary = result["summary"]
            bot_mix = ", ".join(f"{seat}:{data['bot_id']}" for seat, data in summary["seat_bots"].items())
            print(
                f"[xg-data-pump] game {games_completed} seed={seed} "
                f"players={summary['player_count']} winner={summary['winner']} "
                f"qualifier_decisions={summary['decision_count']} bots=[{bot_mix}]"
            )
            if train_if_requested(args, decisions_since_train):
                decisions_since_train = 0
            if args.sleep:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\n[xg-data-pump] interrupted")

    print(f"[xg-data-pump] generated {games_completed} classic games in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
