from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from operations.research import xg_data_pump


class XGDataPumpTests(unittest.TestCase):
    def test_sampler_defaults_to_qualifier_and_excludes_xg_bot(self) -> None:
        qualifier, alternatives = xg_data_pump.load_bot_pool()

        self.assertEqual(qualifier.bot_id, "qualifier_bot")
        self.assertTrue(alternatives)
        self.assertNotIn("qualifier_bot", {descriptor.bot_id for descriptor in alternatives})
        self.assertNotIn("xg_bot", {descriptor.bot_id for descriptor in alternatives})

    def test_one_generated_game_is_classic_and_decision_ready(self) -> None:
        qualifier, alternatives = xg_data_pump.load_bot_pool()

        result = xg_data_pump.run_generated_game(
            seed=123,
            qualifier=qualifier,
            alternatives=alternatives,
            min_players=2,
            max_players=2,
            non_qualifier_probability=0.0,
            require_db=False,
            no_db=True,
            tag="test",
        )

        self.assertEqual(result["summary"]["map"], "classic")
        self.assertEqual(result["summary"]["player_count"], 2)
        self.assertGreater(len(result["decisions"]), 0)
        self.assertTrue(
            all(
                result["summary"]["seat_bots"][row["player"]]["bot_id"] == "qualifier_bot"
                for row in result["decisions"]
            )
        )
        first = result["decisions"][0]
        self.assertEqual(first["state"]["map_name"], "classic")
        self.assertIn("legal_actions", first)
        self.assertIn(first["chosen"], first["legal_actions"])

    def test_non_qualifier_seats_shape_games_without_labels(self) -> None:
        qualifier, alternatives = xg_data_pump.load_bot_pool()

        result = xg_data_pump.run_generated_game(
            seed=124,
            qualifier=qualifier,
            alternatives=alternatives,
            min_players=2,
            max_players=2,
            non_qualifier_probability=1.0,
            require_db=False,
            no_db=True,
            tag="test",
        )

        self.assertGreater(result["summary"]["action_count"], 0)
        self.assertEqual(result["decisions"], [])
        self.assertTrue(
            all(
                seat["bot_id"] != "qualifier_bot"
                for seat in result["summary"]["seat_bots"].values()
            )
        )

    def test_cached_rank_groups_are_precomputed_from_qualifier_decisions(self) -> None:
        qualifier, alternatives = xg_data_pump.load_bot_pool()

        result = xg_data_pump.run_generated_game(
            seed=125,
            qualifier=qualifier,
            alternatives=alternatives,
            min_players=2,
            max_players=2,
            non_qualifier_probability=0.0,
            require_db=False,
            no_db=True,
            tag="test",
        )
        groups = xg_data_pump.cached_rank_groups_from_decisions(result["decisions"])

        self.assertGreater(len(groups), 0)
        self.assertEqual(groups[0]["feature_count"], len(xg_data_pump.xgb_features.feature_names()))
        self.assertIn(1, groups[0]["labels"])
        self.assertEqual(groups[0]["group_size"], len(groups[0]["features"]))

    def test_append_jsonl_writes_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"

            xg_data_pump.append_jsonl(path, [{"a": 1}, {"b": 2}])

            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(rows, [{"a": 1}, {"b": 2}])


if __name__ == "__main__":
    unittest.main()
