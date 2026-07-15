from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_TRAINER = Path(__file__).resolve().parents[2] / "operations" / "research" / "train_xg_bot.py"
_spec = importlib.util.spec_from_file_location("train_xg_bot", _TRAINER)
train_xg_bot = importlib.util.module_from_spec(_spec)
sys.modules["train_xg_bot"] = train_xg_bot
_spec.loader.exec_module(train_xg_bot)

from operations.research import xg_data_pump


def _decision_row() -> dict:
    return {
        "player": "p0",
        "decision": "turn",
        "state": {
            "map_name": "classic",
            "player_count": 2,
            "turn_number": 20,
            "score": 4,
            "trains_remaining": 41,
            "hand": {"R": 4, "L": 1},
            "tickets": [
                {"city1": "Denver", "city2": "El Paso", "value": 4, "completed": False, "impossible": False},
            ],
            "market": ["R", "B", "G", "O", "Y"],
            "discard": {},
            "train_cards_in_deck": 70,
            "tickets_in_deck": 20,
            "claimed_by": {},
            "opponents": [
                {"player_id": "p1", "exposed": {}, "hand_count": 8, "trains": 39, "score": 7, "ticket_count": 3},
            ],
            "ticket_offer": None,
        },
        "legal_actions": [
            {"type": "DrawBlind"},
            {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
        ],
        "chosen": {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
    }


class TrainXGBotTests(unittest.TestCase):
    def test_build_rank_dataset_creates_one_group_per_decision(self) -> None:
        rows = [_decision_row(), _decision_row()]

        feature_rows, labels, group_sizes, groups = train_xg_bot.build_rank_dataset(rows)

        self.assertEqual(len(groups), 2)
        self.assertEqual(group_sizes, [2, 2])
        self.assertEqual(labels, [0, 1, 0, 1])
        self.assertEqual(len(feature_rows), 4)

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "numpy optional extra is not installed")
    def test_build_cached_rank_dataset_uses_precomputed_groups(self) -> None:
        cached_groups = xg_data_pump.cached_rank_groups_from_decisions([_decision_row(), _decision_row()])

        matrix, labels, group_sizes, groups = train_xg_bot.build_cached_rank_dataset(cached_groups)

        self.assertEqual(matrix.shape[0], 4)
        self.assertEqual(len(labels), 4)
        self.assertEqual(group_sizes, [2, 2])
        self.assertEqual(len(groups), 2)

    @unittest.skipIf(importlib.util.find_spec("xgboost") is None, "xgboost optional extra is not installed")
    def test_training_smoke_writes_model_and_schema(self) -> None:
        rows = [_decision_row() for _ in range(12)]
        cached_groups = xg_data_pump.cached_rank_groups_from_decisions(rows)

        model, schema, train_report = train_xg_bot.train_ranker_from_cached_groups(
            cached_groups,
            n_estimators=20,
            max_depth=2,
        )

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "ranker.json"
            features_path = Path(tmp) / "features.json"
            model.save_model(str(model_path))
            train_xg_bot.write_feature_schema(features_path, schema=schema, model_path=model_path, report=train_report)

            self.assertTrue(model_path.exists())
            self.assertTrue(features_path.exists())
            self.assertGreater(train_report["top1_accuracy"], train_report["uniform_menu_baseline"])


if __name__ == "__main__":
    unittest.main()
