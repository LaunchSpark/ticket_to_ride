from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from ticket_to_ride.engine.replay import GameRecord, record_of

from external.bots.fable_best_bot import FableBestBot
from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_game

_EXPORTER = Path(__file__).resolve().parents[2] / "operations" / "research" / "decision_export.py"
_spec = importlib.util.spec_from_file_location("decision_export", _EXPORTER)
decision_export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decision_export)


class DecisionExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness_game = initialize_game([FableBestBot(), RandomBot()], seed=29)
        harness_game.play()
        cls.game = harness_game.game
        cls.record = record_of(cls.game)
        cls.rows = decision_export.decisions_from_record(
            cls.record, {"tag": "test", "seed": 29}
        )

    def test_one_decision_row_per_recorded_action(self):
        self.assertEqual(len(self.rows), len(self.record.actions))

    def test_chosen_action_is_always_in_the_legal_menu(self):
        for row in self.rows:
            self.assertIn(row["chosen"], row["legal_actions"])

    def test_symbolic_state_carries_the_full_public_picture(self):
        row = next(r for r in self.rows if r["decision"] == "turn")
        state = row["state"]
        for key in ("map_name", "hand", "tickets", "market", "discard",
                    "claimed_by", "opponents", "trains_remaining",
                    "train_cards_in_deck", "tickets_in_deck"):
            self.assertIn(key, state)
        self.assertEqual(state["map_name"], "classic")
        self.assertEqual(row["state_schema_version"], 1)

    def test_keep_decisions_include_the_offer(self):
        keep_rows = [r for r in self.rows if r["decision"] == "keep_tickets"]
        self.assertTrue(keep_rows)
        for row in keep_rows:
            self.assertTrue(row["state"]["ticket_offer"])

    def test_outcome_matches_the_original_game(self):
        scores = self.game.context.scores
        for row in self.rows:
            self.assertEqual(row["outcome"]["final_score"], scores[row["player"]])

    def test_round_trips_through_json_record(self):
        restored = GameRecord.from_dict(self.record.to_dict())
        again = decision_export.decisions_from_record(restored, {"tag": "test", "seed": 29})
        self.assertEqual(again, self.rows)


if __name__ == "__main__":
    unittest.main()
