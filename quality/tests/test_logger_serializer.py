from collections import Counter
from types import SimpleNamespace
import unittest

from ticket_to_ride.logging.game_logger import GameLogSerializer


class FakeRoute:
    def __init__(self, route_id: str, route_label: str) -> None:
        self.route_id = route_id
        self.route_label = route_label

    def __repr__(self) -> str:
        return self.route_id


class FakeMap:
    def __init__(self, claimed_routes):
        self.claimed_routes = claimed_routes

    def get_claimed_routes(self, player_id: str):
        return self.claimed_routes.get(player_id, [])


class SerializerTests(unittest.TestCase):
    def test_serialize_turn_state_matches_viewer_shape(self) -> None:
        serializer = GameLogSerializer()
        fake_map = FakeMap(
            {
                "bot_1": [FakeRoute("Seattle-Portland-1", "Seattle-Portland-X")],
                "bot_2": [FakeRoute("Helena-Denver-1", "Helena-Denver-G")],
            }
        )

        current_player = SimpleNamespace(
            player_id="bot_1",
            name="Alpha",
            color="red",
            trains_remaining=41,
            get_tickets=lambda: [
                SimpleNamespace(city1="Seattle", city2="Helena", value=9, is_completed=False)
            ],
            get_hand=lambda: Counter({"R": 2, "L": 1}),
        )

        context = SimpleNamespace(
            player_id="bot_1",
            score=12,
            map=fake_map,
            face_up_cards=["R", "G", "L", "U", "W"],
            opponents=[
                SimpleNamespace(
                    player_id="bot_2",
                    score=8,
                    remaining_trains=39,
                    destination_ticket_count=3,
                    num_cards_in_hand=6,
                    exposed_hand=Counter({"B": 1, "Y": 2}),
                )
            ],
        )

        turn_state = serializer.serialize_turn_state([current_player], context)

        self.assertEqual(turn_state["player"]["playerId"], "bot_1")
        self.assertEqual(turn_state["player"]["remainingTrains"], 41)
        self.assertEqual(turn_state["player"]["hand"]["red"], 2)
        self.assertEqual(turn_state["player"]["hand"]["locomotive"], 1)
        self.assertEqual(
            turn_state["player"]["claimedRoutes"],
            [{"routeId": "Seattle-Portland-1", "routeLabel": "Seattle-Portland-X"}],
        )
        self.assertEqual(
            turn_state["opponents"][0]["claimedRoutes"],
            [{"routeId": "Helena-Denver-1", "routeLabel": "Helena-Denver-G"}],
        )
        self.assertEqual(turn_state["opponents"][0]["hand"]["public"]["yellow"], 2)
        self.assertEqual(turn_state["opponents"][0]["hand"]["hidden"], 3)
        self.assertEqual(turn_state["gameObjects"]["decks"]["marketCards"], ["R", "G", "L", "U", "W"])


if __name__ == "__main__":
    unittest.main()
