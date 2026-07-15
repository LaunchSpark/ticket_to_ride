from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_CURRICULUM = Path(__file__).resolve().parents[2] / "operations" / "research" / "xg_curriculum.py"
_spec = importlib.util.spec_from_file_location("xg_curriculum", _CURRICULUM)
xg_curriculum = importlib.util.module_from_spec(_spec)
sys.modules["xg_curriculum"] = xg_curriculum
_spec.loader.exec_module(xg_curriculum)


def _decision_row() -> dict:
    return {
        "player": "bot_0",
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
                {"player_id": "bot_1", "exposed": {}, "hand_count": 8, "trains": 39, "score": 7, "ticket_count": 3},
            ],
            "ticket_offer": None,
        },
        "legal_actions": [
            {"type": "DrawBlind"},
            {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
        ],
        "chosen": {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
    }


class XGCurriculumTests(unittest.TestCase):
    def test_winning_decisions_become_weighted_groups(self) -> None:
        groups = xg_curriculum.outcome_cached_groups_from_decisions(
            [_decision_row()],
            margin=24,
            won=True,
        )

        self.assertEqual(len(groups), 1)
        self.assertGreater(groups[0]["group_weight"], 1.0)
        self.assertGreater(groups[0]["outcome_reward"], 1.0)
        self.assertIn(groups[0]["outcome_reward"], groups[0]["labels"])

    def test_losing_decisions_are_not_reinforced(self) -> None:
        groups = xg_curriculum.outcome_cached_groups_from_decisions(
            [_decision_row()],
            margin=-12,
            won=False,
        )

        self.assertEqual(groups, [])

    @unittest.skipIf(importlib.util.find_spec("xgboost") is None, "xgboost optional extra is not installed")
    def test_curriculum_game_captures_xg_decisions(self) -> None:
        model_in = xg_curriculum.DEFAULT_MODEL_IN
        features_in = xg_curriculum.DEFAULT_FEATURES_IN
        if not model_in.exists() or not features_in.exists():
            self.skipTest("XG Bot baseline artifacts do not exist")
        opponent = xg_curriculum.load_opponent("random_bot")

        result = xg_curriculum.run_curriculum_game(
            seed=987,
            opponent=opponent,
            model_path=model_in,
            features_path=features_in,
            epsilon=0.0,
            xg_first=True,
            stage_index=0,
            tag="test",
        )

        self.assertEqual(result.summary["captured_bot_id"], "xg_bot")
        self.assertEqual(result.summary["opponent_bot_id"], "random_bot")
        self.assertGreater(result.summary["decision_count"], 0)
        self.assertTrue(all(row["player"] == result.summary["xg_player"] for row in result.decisions))

    @unittest.skipIf(importlib.util.find_spec("xgboost") is None, "xgboost optional extra is not installed")
    def test_weighted_cached_groups_train(self) -> None:
        train_xg_bot = xg_curriculum.train_xg_bot
        groups = xg_curriculum.outcome_cached_groups_from_decisions(
            [_decision_row() for _ in range(6)],
            margin=20,
            won=True,
        )

        model, schema, report = train_xg_bot.train_ranker_from_cached_groups(
            groups,
            n_estimators=5,
            max_depth=2,
        )

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "ranker.json"
            features_path = Path(tmp) / "features.json"
            model.save_model(str(model_path))
            train_xg_bot.write_feature_schema(features_path, schema=schema, model_path=model_path, report=report)
            self.assertTrue(model_path.exists())
            self.assertTrue(features_path.exists())


if __name__ == "__main__":
    unittest.main()
