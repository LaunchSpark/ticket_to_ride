import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from external.contracts.abstract_interface import Interface
from ticket_to_ride.backend.runtime.executor import BotApiExecutor, InProcessBotExecutor
from ticket_to_ride.engine.actions import DrawBlind, Pass
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


def build_test_players() -> list[Player]:
    players = [
        Player("seat_1", Interface(), "Seat One", "red"),
        Player("seat_2", Interface(), "Seat Two", "blue"),
    ]
    context = GameContext([player.player_id for player in players])
    for player in players:
        player.attach(context, players)
        player.set_context(PlayerView(player.player_id, context, players))
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


class InProcessBotExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player = build_test_players()[0]

    @staticmethod
    def _loader(bot_class):
        return SimpleNamespace(
            load_bots=lambda: {
                "menu_bot": SimpleNamespace(bot_class=bot_class),
            }
        )

    def test_action_bot_receives_and_returns_canonical_legal_action(self) -> None:
        class LastActionBot:
            def act(self, view, legal_actions):
                self.seen_view = view
                self.seen_actions = legal_actions
                return legal_actions[-1]

        executor = InProcessBotExecutor("menu_bot", loader=self._loader(LastActionBot))
        executor.start()
        legal_actions = [DrawBlind(), Pass()]

        result = executor.invoke(
            "act",
            player=self.player,
            timeout_ms=100,
            remaining_time_ms=1000,
            initial_time_ms=1000,
            increment_ms=0,
            args=("safe-view", legal_actions),
        )

        self.assertEqual(result.status, "ok")
        self.assertIs(result.payload, legal_actions[-1])
        self.assertEqual(executor.bot.seen_view, "safe-view")
        self.assertIs(executor.bot.seen_actions, legal_actions)

    def test_bot_exception_is_a_runtime_result(self) -> None:
        class ExplodingBot:
            def act(self, view, legal_actions):
                raise RuntimeError("boom")

        executor = InProcessBotExecutor("menu_bot", loader=self._loader(ExplodingBot))
        executor.start()
        result = executor.invoke(
            "act",
            player=self.player,
            timeout_ms=100,
            remaining_time_ms=1000,
            initial_time_ms=1000,
            increment_ms=0,
            args=("safe-view", [Pass()]),
        )

        self.assertEqual(result.status, "bot_exception")
        self.assertEqual(result.detail, "boom")

    def test_elapsed_hard_limit_is_reported(self) -> None:
        class FastBot:
            def act(self, view, legal_actions):
                return legal_actions[0]

        executor = InProcessBotExecutor("menu_bot", loader=self._loader(FastBot))
        executor.start()
        with patch(
            "ticket_to_ride.backend.runtime.executor.time.monotonic",
            side_effect=[1.0, 1.050],
        ):
            result = executor.invoke(
                "act",
                player=self.player,
                timeout_ms=10,
                remaining_time_ms=1000,
                initial_time_ms=1000,
                increment_ms=0,
                args=("safe-view", [Pass()]),
            )

        self.assertEqual(result.status, "per_call_timeout")
        self.assertEqual(result.elapsed_ms, 50)


if __name__ == "__main__":
    unittest.main()
