import socket
import unittest
from unittest.mock import patch
from urllib.error import URLError

from external.contracts.abstract_interface import Interface
from ticket_to_ride.backend.runtime.executor import BotApiExecutor
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.player_context import PlayerContext


def build_test_players() -> list[Player]:
    players = [
        Player("seat_1", Interface(), "Seat One", "red"),
        Player("seat_2", Interface(), "Seat Two", "blue"),
    ]
    context = GameContext([player.player_id for player in players])
    for player in players:
        player.set_context(PlayerContext(player.player_id, context, players))
    return players


class BotApiExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = build_test_players()
        self.player = self.players[0]

    def test_start_and_close_manage_session_lifecycle(self) -> None:
        executor = BotApiExecutor("random_bot")
        with patch.object(BotApiExecutor, "_request", side_effect=[{"sessionId": "session-1"}, {}]) as request:
            executor.start()
            result = executor.close()

        self.assertEqual(result.status, "ok")
        self.assertIsNone(executor.session_id)
        self.assertEqual(request.call_args_list[0].args[0:3], ("POST", "/bot-sessions", {"botId": "random_bot"}))
        self.assertEqual(request.call_args_list[1].args[0:3], ("DELETE", "/bot-sessions/session-1", None))

    def test_timeout_maps_to_per_call_timeout(self) -> None:
        executor = BotApiExecutor("random_bot")
        executor.session_id = "session-1"
        with patch.object(BotApiExecutor, "_request", side_effect=socket.timeout):
            result = executor.invoke(
                "choose_turn_action",
                player=self.player,
                timeout_ms=50,
                remaining_time_ms=200,
                initial_time_ms=200,
                increment_ms=0,
                args=(),
            )

        self.assertEqual(result.status, "per_call_timeout")

    def test_invalid_response_maps_to_invalid_response(self) -> None:
        executor = BotApiExecutor("random_bot")
        executor.session_id = "session-1"
        with patch.object(BotApiExecutor, "_request", return_value={"action": 9}):
            result = executor.invoke(
                "choose_turn_action",
                player=self.player,
                timeout_ms=50,
                remaining_time_ms=200,
                initial_time_ms=200,
                increment_ms=0,
                args=(),
            )

        self.assertEqual(result.status, "invalid_response")

    def test_transport_error_maps_from_urlerror(self) -> None:
        executor = BotApiExecutor("random_bot")
        executor.session_id = "session-1"
        with patch.object(BotApiExecutor, "_request", side_effect=URLError("boom")):
            result = executor.invoke(
                "choose_turn_action",
                player=self.player,
                timeout_ms=50,
                remaining_time_ms=200,
                initial_time_ms=200,
                increment_ms=0,
                args=(),
            )

        self.assertEqual(result.status, "transport_error")


if __name__ == "__main__":
    unittest.main()
