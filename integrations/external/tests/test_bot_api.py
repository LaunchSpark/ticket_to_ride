from collections import Counter
from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient

from external.clients.bot_api.app import create_app
from external.clients.bot_api.loader import BotDescriptor
from external.clients.bot_api.models import BotMetadata
from external.clients.bot_api.service import BotSessionManager
from external.clients.python.api_interface import ApiBotInterface
from external.contracts.base_bot import BaseBot
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.map import Route


class TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method: str, path: str, payload=None):
        response = self.client.request(method, path, json=payload)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class DeterministicBot(BaseBot):
    META = {
        "schema_version": 1,
        "id": "deterministic_bot",
        "name": "Deterministic Bot",
        "version": "1.0.0",
        "description": "Always picks the same legal options.",
    }

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
        descriptor = BotDescriptor(
            bot_id="deterministic_bot",
            metadata=BotMetadata.from_module_meta(DeterministicBot.META),
            bot_class=DeterministicBot,
            module_name="tests.deterministic_bot",
            module_path="tests/deterministic_bot.py",
        )
        session_manager = BotSessionManager(descriptors={"deterministic_bot": descriptor})
        self.client = TestClient(create_app(session_manager=session_manager))
        self.interface = ApiBotInterface("deterministic_bot", transport=TestClientTransport(self.client))
        self.player = self._build_player()
        self.interface.set_player(self.player)

    def test_api_interface_round_trips_bot_choices(self) -> None:
        metadata_response = self.client.get("/bots")
        self.assertEqual(metadata_response.status_code, 200)
        self.assertEqual(metadata_response.json()[0]["botId"], "deterministic_bot")

        self.assertEqual(self.interface.choose_turn_action(), 2)
        self.assertEqual(self.interface.choose_draw_train_action(), -1)

        route_one = Route("Seattle", "Portland", 1, "X", "Seattle-Portland-1")
        route_two = Route("Helena", "Denver", 4, "G", "Helena-Denver-1")
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

    def test_bot_execution_errors_return_structured_response_without_crashing_service(self) -> None:
        class ExplodingBot(BaseBot):
            META = {
                "schema_version": 1,
                "id": "exploding_bot",
                "name": "Exploding Bot",
                "version": "1.0.0",
                "description": "Raises during move selection.",
            }

            def choose_turn_action(self):
                raise RuntimeError("boom")

            def choose_draw_train_action(self) -> int:
                return -1

            def choose_route_to_claim(self, claimable_routes):
                return claimable_routes[0]

            def choose_color_to_spend(self, route, color_options):
                return None

            def select_ticket_offer(self, offer):
                return offer[:1]

        exploding_descriptor = BotDescriptor(
            bot_id="exploding_bot",
            metadata=BotMetadata.from_module_meta(ExplodingBot.META),
            bot_class=ExplodingBot,
            module_name="tests.exploding_bot",
            module_path="tests/exploding_bot.py",
        )
        client = TestClient(create_app(session_manager=BotSessionManager(descriptors={"exploding_bot": exploding_descriptor})))
        session_response = client.post("/bot-sessions", json={"botId": "exploding_bot"})
        self.assertEqual(session_response.status_code, 200)

        response = client.post(
            f"/bot-sessions/{session_response.json()['sessionId']}/choose-turn-action",
            json={"playerState": self.interface._serialize_player_state()},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["botId"], "exploding_bot")
        self.assertEqual(response.json()["action"], "choose_turn_action")
        self.assertEqual(response.json()["errorType"], "bot_exception")
        self.assertIn("boom", response.json()["detail"])

    def test_delete_bot_session_removes_session(self) -> None:
        response = self.client.delete(f"/bot-sessions/{self.interface.session_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "deleted")

        missing_response = self.client.delete(f"/bot-sessions/{self.interface.session_id}")
        self.assertEqual(missing_response.status_code, 404)

    @staticmethod
    def _build_player():
        class CountDeck:
            def __init__(self, count: int) -> None:
                self.count = count

            def __len__(self) -> int:
                return self.count

        routes = [
            Route("Seattle", "Portland", 1, "X", "Seattle-Portland-1"),
            Route("Helena", "Denver", 4, "G", "Helena-Denver-1"),
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
