"""Train the explainable XG Bot state-action ranker from cached pump groups.

The xg_data_pump writes one cached ranking group per captured QualifierBot
decision. Each group already contains dense state-action features, labels, and
menu metadata, so this trainer can spend its time boosting instead of rebuilding
route and ticket features from raw DecisionRecord rows.

    uv run --extra xgb python operations/research/train_xg_bot.py --limit 5000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations"))

from external.ml import xgb_features  # noqa: E402

RESULTS_DIR = REPO / "operations" / "research" / "results"
DECISIONS_FILE = RESULTS_DIR / "decisions.jsonl"
FEATURE_ROWS_FILE = RESULTS_DIR / "xg_pump_feature_rows.jsonl"
MODEL_FILE = RESULTS_DIR / "xg_bot_ranker.json"
FEATURES_FILE = RESULTS_DIR / "xg_bot_features.json"


@dataclass(frozen=True)
class GroupMeta:
    start: int
    size: int
    chosen_index: int
    decision: str
    map_name: str


def load_decisions(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def load_cached_groups(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    groups = []
    if not path.exists():
        return groups
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            groups.append(json.loads(line))
            if limit is not None and len(groups) >= limit:
                break
    return groups


def build_rank_dataset(rows: list[dict[str, Any]]) -> tuple[list[dict[str, float]], list[int], list[int], list[GroupMeta]]:
    feature_rows: list[dict[str, float]] = []
    labels: list[float] = []
    group_sizes: list[int] = []
    groups: list[GroupMeta] = []

    for row in rows:
        legal_actions = list(row.get("legal_actions") or [])
        chosen_index = xgb_features.chosen_action_index(row)
        if chosen_index is None or not legal_actions:
            continue
        start = len(feature_rows)
        action_rows = xgb_features.build_action_feature_rows(row, legal_actions)
        feature_rows.extend(action_rows)
        labels.extend(1 if index == chosen_index else 0 for index in range(len(action_rows)))
        group_sizes.append(len(action_rows))
        state = row.get("state") or {}
        groups.append(
            GroupMeta(
                start=start,
                size=len(action_rows),
                chosen_index=chosen_index,
                decision=str(row.get("decision") or state.get("decision") or "turn"),
                map_name=str(state.get("map_name") or row.get("map") or "classic"),
            )
        )

    return feature_rows, labels, group_sizes, groups


def build_cached_rank_dataset(
    cached_groups: list[dict[str, Any]],
    *,
    schema: list[str] | None = None,
    include_group_weights: bool = False,
) -> tuple[Any, Any, list[int], list[GroupMeta]] | tuple[Any, Any, list[int], list[GroupMeta], list[float]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Install the optional XG Bot dependencies with: uv sync --extra xgb") from exc

    feature_schema = list(schema or xgb_features.feature_names())
    features: list[list[float]] = []
    labels: list[int] = []
    group_sizes: list[int] = []
    groups: list[GroupMeta] = []
    group_weights: list[float] = []

    for cached in cached_groups:
        group_features = list(cached.get("features") or [])
        group_labels = list(cached.get("labels") or [])
        chosen_index = cached.get("chosen_index")
        if chosen_index is None:
            chosen_index = next((index for index, label in enumerate(group_labels) if label), None)
        if (
            chosen_index is None
            or not group_features
            or len(group_features) != len(group_labels)
            or int(cached.get("feature_count") or len(feature_schema)) != len(feature_schema)
        ):
            continue
        start = len(features)
        features.extend(group_features)
        labels.extend(float(label) for label in group_labels)
        group_sizes.append(len(group_features))
        group_weights.append(float(cached.get("group_weight", 1.0)))
        groups.append(
            GroupMeta(
                start=start,
                size=len(group_features),
                chosen_index=int(chosen_index),
                decision=str(cached.get("decision") or "turn"),
                map_name=str(cached.get("map") or "classic"),
            )
        )

    if not groups:
        empty = (
            np.empty((0, len(feature_schema)), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            [],
            [],
        )
        return (*empty, []) if include_group_weights else empty
    dataset = (
        np.asarray(features, dtype=np.float32),
        np.asarray(labels, dtype=np.float32),
        group_sizes,
        groups,
    )
    return (*dataset, group_weights) if include_group_weights else dataset


def filter_rows_by_maps(rows: list[dict[str, Any]], map_names: set[str] | None) -> list[dict[str, Any]]:
    if not map_names:
        return list(rows)
    return [row for row in rows if _row_map(row) in map_names]


def evaluate_ranker(model: Any, rows: list[dict[str, Any]], schema: list[str]) -> dict[str, Any]:
    feature_rows, labels, group_sizes, groups = build_rank_dataset(rows)
    if not groups:
        return {
            "groups": 0,
            "actions": 0,
            "top1_accuracy": 0.0,
            "mean_reciprocal_rank": 0.0,
            "uniform_menu_baseline": 0.0,
            "per_decision_type": {},
        }

    matrix = xgb_features.vectorize(feature_rows, schema)
    scores = list(_predict_scores(model, matrix))
    return rank_report_from_scores(scores, groups, len(labels))


def rank_report_from_scores(scores: Any, groups: list[GroupMeta], action_count: int) -> dict[str, Any]:
    if not groups:
        return {
            "groups": 0,
            "actions": 0,
            "top1_accuracy": 0.0,
            "mean_reciprocal_rank": 0.0,
            "uniform_menu_baseline": 0.0,
            "per_decision_type": {},
        }

    correct = 0
    reciprocal = 0.0
    uniform = 0.0
    per_type: dict[str, dict[str, int]] = {}

    for group in groups:
        indices = list(range(group.size))
        ranked = sorted(indices, key=lambda index: (-float(scores[group.start + index]), index))
        predicted = ranked[0]
        rank = ranked.index(group.chosen_index) + 1
        hit = predicted == group.chosen_index
        correct += int(hit)
        reciprocal += 1.0 / rank
        uniform += 1.0 / group.size
        bucket = per_type.setdefault(group.decision, {"correct": 0, "total": 0})
        bucket["correct"] += int(hit)
        bucket["total"] += 1

    return {
        "groups": len(groups),
        "actions": action_count,
        "top1_accuracy": correct / len(groups),
        "mean_reciprocal_rank": reciprocal / len(groups),
        "uniform_menu_baseline": uniform / len(groups),
        "per_decision_type": {
            decision: {
                "accuracy": values["correct"] / values["total"] if values["total"] else 0.0,
                "correct": values["correct"],
                "total": values["total"],
            }
            for decision, values in sorted(per_type.items())
        },
    }


def train_ranker(
    rows: list[dict[str, Any]],
    *,
    n_estimators: int = 250,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    seed: int = 7,
    tree_method: str = "hist",
) -> tuple[Any, list[str], dict[str, Any]]:
    try:
        import numpy as np
        import xgboost as xgb
    except ImportError as exc:
        raise SystemExit("Install the optional XG Bot dependencies with: uv sync --extra xgb") from exc

    schema = xgb_features.feature_names()
    feature_rows, labels, group_sizes, groups = build_rank_dataset(rows)
    if not groups:
        raise SystemExit("No usable decision groups found. Run decision_export.py first.")

    matrix = xgb_features.vectorize(feature_rows, schema)
    label_array = np.asarray(labels, dtype=np.float32)
    dmatrix = xgb.DMatrix(matrix, label=label_array)
    dmatrix.set_group(group_sizes)
    model = xgb.train(
        {
            "objective": "rank:pairwise",
            "eval_metric": "ndcg@1",
            "eta": learning_rate,
            "max_depth": max_depth,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "tree_method": tree_method,
            "seed": seed,
        },
        dmatrix,
        num_boost_round=n_estimators,
        verbose_eval=False,
    )
    train_report = evaluate_ranker(model, rows, schema)
    return model, schema, train_report


def train_ranker_from_cached_groups(
    cached_groups: list[dict[str, Any]],
    *,
    n_estimators: int = 250,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    seed: int = 7,
    tree_method: str = "hist",
    xgb_model: Any = None,
) -> tuple[Any, list[str], dict[str, Any]]:
    try:
        import xgboost as xgb
    except ImportError as exc:
        raise SystemExit("Install the optional XG Bot dependencies with: uv sync --extra xgb") from exc

    schema = xgb_features.feature_names()
    matrix, labels, group_sizes, groups, group_weights = build_cached_rank_dataset(
        cached_groups,
        schema=schema,
        include_group_weights=True,
    )
    if not groups:
        raise SystemExit("No usable cached decision groups found.")

    dmatrix = xgb.DMatrix(matrix, label=labels)
    dmatrix.set_group(group_sizes)
    if any(weight != 1.0 for weight in group_weights):
        dmatrix.set_weight(group_weights)
    model = xgb.train(
        {
            "objective": "rank:pairwise",
            "eval_metric": "ndcg@1",
            "eta": learning_rate,
            "max_depth": max_depth,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "tree_method": tree_method,
            "seed": seed,
        },
        dmatrix,
        num_boost_round=n_estimators,
        xgb_model=xgb_model,
        verbose_eval=False,
    )
    train_report = rank_report_from_scores(model.predict(dmatrix), groups, len(labels))
    return model, schema, train_report


def write_feature_schema(path: Path, *, schema: list[str], model_path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "created_at_unix": int(time.time()),
        "feature_names": schema,
        "model_path": str(model_path),
        "train_report": report,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-rows", type=Path, default=FEATURE_ROWS_FILE)
    parser.add_argument("--limit", type=int, default=None, help="max cached Qualifier decision groups to read")
    parser.add_argument("--model-out", type=Path, default=MODEL_FILE)
    parser.add_argument("--features-out", type=Path, default=FEATURES_FILE)
    parser.add_argument("--n-estimators", type=int, default=250)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--tree-method", default="hist")
    args = parser.parse_args()

    if not args.feature_rows.exists():
        raise SystemExit(f"No cached feature rows at {args.feature_rows}. Run xg_data_pump.py first.")

    cached_groups = load_cached_groups(args.feature_rows, limit=args.limit)
    if not cached_groups:
        raise SystemExit("No cached Qualifier decision groups found.")

    started = time.perf_counter()
    model, schema, train_report = train_ranker_from_cached_groups(
        cached_groups,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        seed=args.seed,
        tree_method=args.tree_method,
    )

    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(args.model_out))
    write_feature_schema(args.features_out, schema=schema, model_path=args.model_out, report=train_report)

    report = {
        "cached_groups": len(cached_groups),
        "train": train_report,
        "model_out": str(args.model_out),
        "features_out": str(args.features_out),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _parse_maps(raw: str) -> set[str] | None:
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return values or None


def _row_map(row: dict[str, Any]) -> str:
    state = row.get("state") or {}
    return str(state.get("map_name") or row.get("map") or "classic")


def _predict_scores(model: Any, matrix: Any) -> Any:
    if model.__class__.__name__ == "Booster":
        import xgboost as xgb

        return model.predict(xgb.DMatrix(matrix))
    return model.predict(matrix)


if __name__ == "__main__":
    main()
