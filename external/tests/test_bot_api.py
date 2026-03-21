from collections import Counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from external.contracts.abstract_interface import Interface
from external.clients.python.api_interface import ApiBotInterface
from external.clients.bot_api.app import create_app
from external.clients.bot_api.service import BotSessionManager
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket


class TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method: str, path: str, payload=None):
        response = self.client.request(method, path, json=payload)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class DeterministicBot(Interface):
    def choose_turn_action(self):
        return 2

    def choose_draw_train_action(self) -> int:
        return -1

    def choose_route_to_claim(self, claimable_routes):
        return claimable_routes[1]

    def choose_color_to_spend(self, route, color_options):
        return color_options[-1]

    def select_ticket_offer(self, offer):
        return [offer[0], offer[2]]


class BotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        session_manager = BotSessionManager()
        with patch.object(BotSessionManager, "_load_bot_class", return_value=DeterministicBot):
            self.client = TestClient(create_app(session_manager=session_manager))
            self.interface = ApiBotInterface("DeterministicBot", transport=TestClientTransport(self.client))
            self.player = self._build_player()
            self.interface.set_player(self.player)

    def test_api_interface_round_trips_bot_choices(self) -> None:
        self.assertEqual(self.interface.choose_turn_action(), 2)
        self.assertEqual(self.interface.choose_draw_train_action(), -1)

        route_one = Route("Seattle", "Portland", 1, "X")
        route_two = Route("Helena", "Denver", 4, "G")
        chosen_route, locomotives = self.interface.choose_route_to_claim([(route_one, 0), (route_two, 1)])
        self.assertEqual(repr(chosen_route), repr(route_two))
        self.assertEqual(locomotives, 1)

        self.assertEqual(self.interface.choose_color_to_spend(route_one, ["R", "B", "G"]), "G")

        offer = [
            DestinationTicket("Seattle", "Helena", 9),
            DestinationTicket("Denver", "Omaha", 4),
            DestinationTicket("Chicago", "Miami", 12),
        ]
        chosen_tickets = self.interface.select_ticket_offer(offer)
        self.assertEqual(len(chosen_tickets), 2)
        self.assertEqual(chosen_tickets[0].city1, "Seattle")
        self.assertEqual(chosen_tickets[1].city1, "Chicago")

    @staticmethod
    def _build_player():
        class CountDeck:
            def __init__(self, count: int) -> None:
                self.count = count

            def __len__(self) -> int:
                return self.count

        routes = [
            Route("Seattle", "Portland", 1, "X"),
            Route("Helena", "Denver", 4, "G"),
        ]
        fake_map = SimpleNamespace(routes=routes)
        fake_context = SimpleNamespace(
            face_up_cards=["R", "G", "L", "U", "W"],
            turn_number=3,
            score=11,
            train_deck=CountDeck(25),
            ticket_deck=CountDeck(12),
            opponents=[
                SimpleNamespace(
                    player_id="bot_2",
                    exposed_hand=Counter({"B": 1}),
                    num_cards_in_hand=4,
                    remaining_trains=39,
                    score=8,
                    destination_ticket_count=2,
                )
            ],
            map=fake_map,
        )
        return SimpleNamespace(
            player_id="bot_1",
            name="Alpha",
            color="red",
            trains_remaining=41,
            context=fake_context,
            get_hand=lambda: Counter({"R": 2, "L": 1}),
            get_exposed=lambda: Counter({"R": 1}),
            get_tickets=lambda: [DestinationTicket("Seattle", "Helena", 9)],
        )


if __name__ == "__main__":
    unittest.main()
