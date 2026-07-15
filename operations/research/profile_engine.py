"""Engine hot-path profiler and seeded parity dumper.

Two modes over the same fixed-seed batch of games (FableBestBot +
QualifierBot + two RandomBots on the classic map):

    uv run python operations/research/profile_engine.py --profile
        cProfile the batch and print the top functions by cumulative time.

    uv run python operations/research/profile_engine.py --parity-dump out.json
        Run the batch and dump every game's turn snapshots plus final scores
        to JSON. Diff two dumps (before/after an engine change) to prove the
        change is behavior-preserving.

RandomBot draws from the global `random` module, so each game reseeds it
alongside the engine seed to keep the whole batch reproducible.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))

from external.bots.fable_best_bot import FableBestBot       # noqa: E402
from external.bots.qualifier_bot import QualifierBot        # noqa: E402
from external.bots.random_bot import RandomBot               # noqa: E402
from notebook_harness.game_runner import initialize_game     # noqa: E402

DEFAULT_GAMES = 20
BASE_SEED = 20260715


def run_batch(games: int) -> list[dict]:
    """Play the fixed batch; return one result dict per game."""
    results = []
    for index in range(games):
        seed = BASE_SEED + index
        random.seed(seed)  # RandomBot uses the global random module
        harness = initialize_game(
            [FableBestBot(), QualifierBot(), RandomBot(), RandomBot()],
            seed=seed,
        )
        harness.play()
        results.append({
            "seed": seed,
            "scores": dict(harness.game.context.scores),
            "turns": harness.game.turn_index,
            "snapshots": harness.logger.snapshots,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--profile", action="store_true",
                        help="run under cProfile and print hot functions")
    parser.add_argument("--parity-dump", metavar="PATH",
                        help="write per-game snapshots/scores to a JSON file")
    parser.add_argument("--top", type=int, default=25,
                        help="rows of profile output to print")
    args = parser.parse_args()

    if args.profile:
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        run_batch(args.games)
        profiler.disable()
        elapsed = time.perf_counter() - started
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.strip_dirs().sort_stats("cumulative").print_stats(args.top)
        print(f"{args.games} games in {elapsed:.2f}s "
              f"({elapsed / args.games:.3f}s/game)")
        print(stream.getvalue())
        return

    started = time.perf_counter()
    results = run_batch(args.games)
    elapsed = time.perf_counter() - started
    print(f"{args.games} games in {elapsed:.2f}s ({elapsed / args.games:.3f}s/game)")

    if args.parity_dump:
        path = Path(args.parity_dump)
        path.write_text(json.dumps(results, sort_keys=True, indent=1))
        print(f"parity dump -> {path}")


if __name__ == "__main__":
    main()
