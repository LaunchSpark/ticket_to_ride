"""Curriculum trainer that warm-starts from the current XG Bot model.

The imitation pump teaches XG Bot to copy QualifierBot. This runner starts from
those saved weights, plays XG Bot against a ladder of opponents, captures only
XG Bot decisions, and fine-tunes from successful games. It writes separate
curriculum artifacts by default so the live imitation pump can keep running.

    uv run --extra xgb python operations/research/xg_curriculum.py \
        --opponents random_bot,example_bot --games-per-stage 50 --eval-games 20
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

import train_xg_bot  # noqa: E402
import xg_data_pump  # noqa: E402
from external.bots.xg_bot import XGBot  # noqa: E402
from external.clients.bot_api.loader import BotDescriptor, BotLoader  # noqa: E402
from ticket_to_ride.engine.game import Game  # noqa: E402
from ticket_to_ride.engine.player import Player  # noqa: E402
from ticket_to_ride.engine.replay import record_of  # noqa: E402
from ticket_to_ride.engine.state.game_context import GameContext  # noqa: E402


CLASSIC_MAP = "classic"
RESULTS_DIR = REPO / "operations" / "research" / "results"
DEFAULT_MODEL_IN = RESULTS_DIR / "xg_bot_ranker.json"
DEFAULT_FEATURES_IN = RESULTS_DIR / "xg_bot_features.json"
DEFAULT_MODEL_OUT = RESULTS_DIR / "xg_bot_curriculum_ranker.json"
DEFAULT_FEATURES_OUT = RESULTS_DIR / "xg_bot_curriculum_features.json"
DEFAULT_RECORDS_OUT = RESULTS_DIR / "xg_curriculum_records.jsonl"
DEFAULT_DECISIONS_OUT = RESULTS_DIR / "xg_curriculum_decisions.jsonl"
DEFAULT_FEATURE_ROWS_OUT = RESULTS_DIR / "xg_curriculum_feature_rows.jsonl"
DEFAULT_GAMES_OUT = RESULTS_DIR / "xg_curriculum_games.jsonl"


@dataclass(frozen=True)
class CurriculumGameResult:
    record: dict[str, Any]
    decisions: list[dict[str, Any]]
    cached_groups: list[dict[str, Any]]
    summary: dict[str, Any]


class EpsilonBot:
    """Small exploration wrapper around a normal bot."""

    def __init__(self, inner: Any, *, rng: random.Random, epsilon: float) -> None:
        self.inner = inner
        self.rng = rng
        self.epsilon = epsilon

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
        if legal_actions and self.rng.random() < self.epsilon:
            return self.rng.choice(legal_actions)
        return self.inner.act(view, legal_actions)


def load_opponent(bot_id: str) -> BotDescriptor:
    descriptors = BotLoader().load_bots()
    try:
        return descriptors[bot_id]
    except KeyError as exc:
        available = ", ".join(sorted(descriptors))
        raise SystemExit(f"Unknown opponent '{bot_id}'. Available bots: {available}") from exc


def run_curriculum_game(
    *,
    seed: int,
    opponent: BotDescriptor,
    model_path: Path,
    features_path: Path,
    epsilon: float,
    xg_first: bool,
    stage_index: int,
    tag: str,
) -> CurriculumGameResult:
    random.seed(seed)
    rng = random.Random(seed)
    xg_bot = EpsilonBot(
        XGBot(model_path=model_path, features_path=features_path),
        rng=random.Random(seed ^ 0x9E3779B1),
        epsilon=epsilon,
    )
    opponent_bot = opponent.bot_class()
    xg_seat = "bot_0" if xg_first else "bot_1"
    opponent_seat = "bot_1" if xg_first else "bot_0"
    decisions: list[xg_data_pump.CapturedDecision] = []
    seat_specs = [
        (xg_seat, "xg_bot", "XG Bot", xg_bot, True),
        (opponent_seat, opponent.bot_id, opponent.metadata.name, opponent_bot, False),
    ]
    seat_specs.sort(key=lambda item: item[0])
    players = [
        Player(
            seat_id,
            xg_data_pump.RecordingBot(bot, seat_id, decisions, capture_decisions=capture),
            f"{name} [{seat_id}]",
            xg_data_pump.PLAYER_COLORS[index % len(xg_data_pump.PLAYER_COLORS)],
        )
        for index, (seat_id, _bot_id, name, bot, capture) in enumerate(seat_specs)
    ]

    context = GameContext([seat_id for seat_id, *_rest in seat_specs], map_name=CLASSIC_MAP, seed=seed)
    game = Game(context, players, xg_data_pump.NullLogger(), 0)
    game.play()

    scores = context.scores
    xg_score = scores[xg_seat]
    opponent_score = scores[opponent_seat]
    margin = xg_score - opponent_score
    won = margin > 0
    meta = {
        "tag": tag,
        "source": "xg_curriculum",
        "seed": seed,
        "map": CLASSIC_MAP,
        "player_count": 2,
        "stage_index": stage_index,
        "opponent_bot_id": opponent.bot_id,
        "captured_bot_id": "xg_bot",
        "xg_player": xg_seat,
        "xg_epsilon": epsilon,
        "seat_bots": {
            xg_seat: {"bot_id": "xg_bot", "name": "XG Bot"},
            opponent_seat: {"bot_id": opponent.bot_id, "name": opponent.metadata.name},
        },
        "replay_match_id": None,
    }
    decision_rows = xg_data_pump.decision_rows_from_capture(decisions, scores=scores, meta=meta)
    cached_groups = outcome_cached_groups_from_decisions(
        decision_rows,
        margin=margin,
        won=won,
    )
    record_row = {**meta, "record": record_of(game).to_dict()}
    summary_row = {
        **meta,
        "scores": scores,
        "winner": max(scores, key=scores.get),
        "xg_score": xg_score,
        "opponent_score": opponent_score,
        "xg_margin": margin,
        "xg_won": won,
        "decision_count": len(decision_rows),
        "trainable_decision_count": len(cached_groups),
        "action_count": len(context.action_log),
    }
    return CurriculumGameResult(
        record=record_row,
        decisions=decision_rows,
        cached_groups=cached_groups,
        summary=summary_row,
    )


def outcome_cached_groups_from_decisions(
    decisions: list[dict[str, Any]],
    *,
    margin: int,
    won: bool,
    schema: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert XG decisions into positive-reward rank groups.

    Losses are intentionally not reinforced. This is a simple cross-entropy
    style curriculum step: explore, keep the decisions from games that beat the
    current opponent, and warm-start the next booster from the current one.
    """
    if not won:
        return []
    reward = 1.0 + min(max(float(margin), 0.0), 80.0) / 80.0
    groups = xg_data_pump.cached_rank_groups_from_decisions(decisions, schema=schema)
    for group in groups:
        group["labels"] = [reward if label else 0.0 for label in group["labels"]]
        group["group_weight"] = reward
        group["outcome_reward"] = reward
        group["xg_margin"] = margin
        group["xg_won"] = won
    return groups


def evaluate_model(
    *,
    opponent: BotDescriptor,
    model_path: Path,
    features_path: Path,
    seed_base: int,
    games: int,
    stage_index: int,
) -> dict[str, Any]:
    if games <= 0:
        return {"games": 0, "win_rate": 0.0, "mean_margin": 0.0}
    wins = 0
    margins: list[int] = []
    for offset in range(games):
        result = run_curriculum_game(
            seed=seed_base + offset,
            opponent=opponent,
            model_path=model_path,
            features_path=features_path,
            epsilon=0.0,
            xg_first=offset % 2 == 0,
            stage_index=stage_index,
            tag="xg-curriculum-eval",
        )
        wins += int(result.summary["xg_won"])
        margins.append(int(result.summary["xg_margin"]))
    return {
        "games": games,
        "win_rate": wins / games,
        "mean_margin": sum(margins) / len(margins),
        "min_margin": min(margins),
        "max_margin": max(margins),
    }


def train_stage(
    *,
    cached_groups: list[dict[str, Any]],
    booster: Any,
    rounds: int,
    max_depth: int,
    learning_rate: float,
    seed: int,
) -> tuple[Any, list[str], dict[str, Any]]:
    if not cached_groups:
        raise SystemExit("No positive-reward XG decisions were captured for this stage.")
    return train_xg_bot.train_ranker_from_cached_groups(
        cached_groups,
        n_estimators=rounds,
        max_depth=max_depth,
        learning_rate=learning_rate,
        seed=seed,
        xgb_model=booster,
    )


def load_booster(model_path: Path) -> Any:
    try:
        import xgboost as xgb
    except ImportError as exc:
        raise SystemExit("Install the optional XG Bot dependencies with: uv sync --extra xgb") from exc
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    return booster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opponents", default="random_bot,example_bot", help="comma-separated opponent bot ids")
    parser.add_argument("--games-per-stage", type=int, default=50)
    parser.add_argument("--eval-games", type=int, default=20)
    parser.add_argument("--seed-base", type=int, default=300_000)
    parser.add_argument("--epsilon", type=float, default=0.08, help="exploration probability during training games")
    parser.add_argument("--rounds", type=int, default=80)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--model-in", type=Path, default=DEFAULT_MODEL_IN)
    parser.add_argument("--features-in", type=Path, default=DEFAULT_FEATURES_IN)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_OUT)
    parser.add_argument("--features-out", type=Path, default=DEFAULT_FEATURES_OUT)
    parser.add_argument("--records-out", type=Path, default=DEFAULT_RECORDS_OUT)
    parser.add_argument("--decisions-out", type=Path, default=DEFAULT_DECISIONS_OUT)
    parser.add_argument("--feature-rows-out", type=Path, default=DEFAULT_FEATURE_ROWS_OUT)
    parser.add_argument("--games-out", type=Path, default=DEFAULT_GAMES_OUT)
    args = parser.parse_args()

    if not args.model_in.exists() or not args.features_in.exists():
        raise SystemExit(f"Missing baseline model/features at {args.model_in} and {args.features_in}.")
    if not 0.0 <= args.epsilon <= 1.0:
        raise SystemExit("--epsilon must be between 0 and 1.")

    opponents = [load_opponent(bot_id.strip()) for bot_id in args.opponents.split(",") if bot_id.strip()]
    if not opponents:
        raise SystemExit("At least one opponent is required.")

    current_model_path = args.model_in
    current_features_path = args.features_in
    booster = load_booster(current_model_path)
    schema = train_xg_bot.xgb_features.feature_names()
    started = time.perf_counter()
    stage_reports = []

    for stage_index, opponent in enumerate(opponents):
        stage_seed = args.seed_base + stage_index * 100_000
        before = evaluate_model(
            opponent=opponent,
            model_path=current_model_path,
            features_path=current_features_path,
            seed_base=stage_seed,
            games=args.eval_games,
            stage_index=stage_index,
        )
        stage_groups: list[dict[str, Any]] = []
        stage_wins = 0
        stage_margins: list[int] = []
        for offset in range(args.games_per_stage):
            result = run_curriculum_game(
                seed=stage_seed + 10_000 + offset,
                opponent=opponent,
                model_path=current_model_path,
                features_path=current_features_path,
                epsilon=args.epsilon,
                xg_first=offset % 2 == 0,
                stage_index=stage_index,
                tag="xg-curriculum-train",
            )
            xg_data_pump.append_jsonl(args.records_out, [result.record])
            xg_data_pump.append_jsonl(args.decisions_out, result.decisions)
            xg_data_pump.append_jsonl(args.feature_rows_out, result.cached_groups)
            xg_data_pump.append_jsonl(args.games_out, [result.summary])
            stage_groups.extend(result.cached_groups)
            stage_wins += int(result.summary["xg_won"])
            stage_margins.append(int(result.summary["xg_margin"]))
            print(
                f"[xg-curriculum] stage={stage_index} opponent={opponent.bot_id} "
                f"game={offset + 1}/{args.games_per_stage} "
                f"won={result.summary['xg_won']} margin={result.summary['xg_margin']} "
                f"trainable={len(result.cached_groups)}"
            )

        train_report = None
        if stage_groups:
            booster, schema, train_report = train_stage(
                cached_groups=stage_groups,
                booster=booster,
                rounds=args.rounds,
                max_depth=args.max_depth,
                learning_rate=args.learning_rate,
                seed=stage_seed,
            )
            args.model_out.parent.mkdir(parents=True, exist_ok=True)
            booster.save_model(str(args.model_out))
            train_xg_bot.write_feature_schema(
                args.features_out,
                schema=schema,
                model_path=args.model_out,
                report=train_report,
            )
            current_model_path = args.model_out
            current_features_path = args.features_out

        after = evaluate_model(
            opponent=opponent,
            model_path=current_model_path,
            features_path=current_features_path,
            seed_base=stage_seed + 50_000,
            games=args.eval_games,
            stage_index=stage_index,
        )
        stage_report = {
            "stage_index": stage_index,
            "opponent": opponent.bot_id,
            "before": before,
            "training_games": args.games_per_stage,
            "training_win_rate": stage_wins / args.games_per_stage if args.games_per_stage else 0.0,
            "training_mean_margin": sum(stage_margins) / len(stage_margins) if stage_margins else 0.0,
            "trainable_groups": len(stage_groups),
            "train": train_report,
            "after": after,
        }
        stage_reports.append(stage_report)
        print(json.dumps(stage_report, indent=2, sort_keys=True))

    final_report = {
        "stages": stage_reports,
        "model_out": str(current_model_path),
        "features_out": str(current_features_path),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    print(json.dumps(final_report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
