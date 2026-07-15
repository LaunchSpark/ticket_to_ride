from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from external.ml import xgb_features
from ticket_to_ride.engine.state.costs import parse_cost


def _base_state() -> dict:
    return {
        "map_name": "classic",
        "player_count": 2,
        "turn_number": 12,
        "score": 8,
        "trains_remaining": 42,
        "hand": {"R": 3, "L": 1},
        "tickets": [
            {"city1": "Denver", "city2": "El Paso", "value": 4, "completed": False, "impossible": False},
        ],
        "market": ["R", "B", "L", "G", "O"],
        "discard": {"Y": 2},
        "train_cards_in_deck": 80,
        "tickets_in_deck": 22,
        "claimed_by": {},
        "opponents": [
            {"player_id": "p1", "exposed": {"B": 1}, "hand_count": 7, "trains": 40, "score": 10, "ticket_count": 3},
        ],
        "ticket_offer": None,
    }


class XGBFeatureTests(unittest.TestCase):
    def test_feature_names_are_stable_and_unique(self) -> None:
        names = xgb_features.feature_names()

        self.assertEqual(names[0], "bias")
        self.assertEqual(len(names), len(set(names)))
        for expected in (
            "decision_turn",
            "action_ClaimRoute",
            "claim_ticket_distance_reduction_norm",
            "draw_estimated_useful_probability",
            "keep_value_per_distance_norm",
        ):
            self.assertIn(expected, names)

    def test_feature_builder_returns_one_row_per_action_and_recovers_label(self) -> None:
        row = {
            "player": "p0",
            "decision": "turn",
            "state": _base_state(),
            "legal_actions": [
                {"type": "DrawBlind"},
                {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
            ],
            "chosen": {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0},
        }

        rows = xgb_features.build_action_feature_rows(row, row["legal_actions"])

        self.assertEqual(len(rows), len(row["legal_actions"]))
        self.assertEqual(xgb_features.chosen_action_index(row), 1)

    def test_claim_route_features_include_route_shape_and_ticket_reduction(self) -> None:
        row = {
            "player": "p0",
            "decision": "turn",
            "state": _base_state(),
        }
        action = {"type": "ClaimRoute", "route_id": "Santa_Fe-Denver-1", "color": "R", "locomotives": 0}

        features = xgb_features.build_action_feature_rows(row, [action])[0]

        self.assertAlmostEqual(features["claim_route_length_norm"], 2 / 8)
        self.assertAlmostEqual(features["claim_route_points_norm"], 2 / 21)
        self.assertEqual(features["claim_route_color_X"], 1.0)
        self.assertGreater(features["claim_ticket_distance_reduction_norm"], 0.0)

    def test_claim_route_features_describe_mixed_cost_shape(self) -> None:
        route = xgb_features.RouteInfo(
            city1="Ax",
            city2="Bx",
            length=4,
            color="X",
            route_id="Ax-Bx-1",
            cost=parse_cost("1L+1(G|B)+2X", 4),
        )
        topology = xgb_features.MapTopology([route])
        row = {"player": "p0", "decision": "turn", "state": _base_state()}
        action = {
            "type": "ClaimRoute",
            "route_id": route.route_id,
            "color": "G",
            "locomotives": 1,
            "payment": [["L", 1], ["G", 0], ["R", 0]],
        }

        with patch.object(xgb_features, "_load_topology", return_value=topology):
            features = xgb_features.build_action_feature_rows(row, [action])[0]

        self.assertAlmostEqual(features["claim_cost_component_count_norm"], 3 / 8)
        self.assertAlmostEqual(features["claim_cost_option_set_count_norm"], 1 / 8)
        self.assertAlmostEqual(features["claim_cost_grey_spaces_norm"], 2 / 8)
        self.assertAlmostEqual(
            features["claim_cost_required_locomotive_spaces_norm"], 1 / 8)
        self.assertAlmostEqual(
            features["claim_cost_distinct_real_colors_norm"], 2 / 8)
        self.assertAlmostEqual(
            features["claim_cost_declared_real_color_options_norm"], 2 / 64)
        self.assertAlmostEqual(features["claim_cost_eligible_G_spaces_norm"], 3 / 8)
        self.assertAlmostEqual(features["claim_cost_eligible_B_spaces_norm"], 3 / 8)
        self.assertAlmostEqual(features["claim_cost_eligible_R_spaces_norm"], 2 / 8)

    def test_keep_ticket_rows_include_value_distance_and_overlap_features(self) -> None:
        state = _base_state()
        state["decision"] = "keep_tickets"
        state["ticket_offer"] = [
            {"city1": "Denver", "city2": "El Paso", "value": 4},
            {"city1": "Seattle", "city2": "New York", "value": 22},
            {"city1": "Boston", "city2": "Miami", "value": 12},
        ]
        row = {"player": "p0", "decision": "keep_tickets", "state": state}
        action = {"type": "KeepTickets", "indices": [0, 2]}

        features = xgb_features.build_action_feature_rows(row, [action])[0]

        self.assertAlmostEqual(features["keep_count_norm"], 2 / 3)
        self.assertGreater(features["keep_total_value_norm"], 0.0)
        self.assertGreater(features["keep_mean_distance_norm"], 0.0)
        self.assertGreater(features["keep_value_per_distance_norm"], 0.0)
        self.assertGreater(features["keep_endpoint_overlap_norm"], 0.0)

    def test_numpy_is_lazy_until_vectorize(self) -> None:
        source_before_vectorize = inspect.getsource(xgb_features).split("def vectorize", 1)[0]

        self.assertNotIn("import numpy", source_before_vectorize)


if __name__ == "__main__":
    unittest.main()
