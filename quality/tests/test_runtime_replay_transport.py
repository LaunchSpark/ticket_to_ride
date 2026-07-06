import unittest

from external.contracts.abstract_interface import Interface
from ticket_to_ride.backend.models import ManagedMatchSeatConfig, TimeControlConfig
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.backend.runtime.models import MatchExecutionContext
from ticket_to_ride.backend.runtime.replay_transport import build_managed_replay_logger
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
        player.set_context(PlayerView(player.player_id, context, players))
    return players


class ReplayTransportTests(unittest.TestCase):
    def test_repository_backed_logger_persists_match_round_and_turn(self) -> None:
        repository = InMemoryMatchRepository()
        match_context = MatchExecutionContext(
            match_id="managed-match",
            name="managed-match",
            seats=[
                ManagedMatchSeatConfig(seatId="seat_1", primaryBotId="slow_bot"),
                ManagedMatchSeatConfig(seatId="seat_2", primaryBotId="steady_bot"),
            ],
            fallback_bot_id="random_bot",
            round_count=1,
            time_control=TimeControlConfig(initialTimeMs=200, incrementMs=0),
            timeout_policy="loss_on_time",
            execution_mode="bot_api",
            bot_names={"slow_bot": "Slow Bot", "steady_bot": "Steady Bot", "random_bot": "Random Bot"},
        )
        logger = build_managed_replay_logger(repository, match_context)
        players = build_test_players()
        logger.set_player_list(players)

        match_id = logger.start_match(match_context.name)
        round_id = logger.start_round(0)
        turn_id = logger.record_turn(0, players[0].context)
        finalize_payload = logger.finalize_match()

        self.assertIn(match_id, repository.matches)
        self.assertIn(round_id, repository.rounds)
        self.assertIn(turn_id, repository.turns)
        self.assertEqual(repository.matches[match_id]["status"], "completed")
        self.assertEqual(finalize_payload["matchId"], match_id)


if __name__ == "__main__":
    unittest.main()
