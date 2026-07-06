import json
import random
import unittest

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.replay import GameRecord, record_of, replay_game
from ticket_to_ride.engine.state.game_context import GameContext


class _NullLogger:
    def record_turn(self, *args, **kwargs):
        return None


class _SeededRandomBot:
    def __init__(self, seed):
        self._rng = random.Random(seed)
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        return self._rng.choice(legal_actions)


def _play_recorded(seed=31):
    players = [Player(f"p{i}", _SeededRandomBot(seed + i), f"p{i}", "red") for i in range(3)]
    context = GameContext([p.player_id for p in players], seed=seed)
    game = Game(context, players, _NullLogger(), 0)
    game.play()
    return game


class ReplayTests(unittest.TestCase):
    def test_replay_reproduces_the_game(self):
        original = _play_recorded()
        record = record_of(original)
        self.assertTrue(record.actions)

        replayed = replay_game(record)
        self.assertEqual(replayed.context.scores, original.context.scores)
        self.assertEqual(
            {r.route_id: r.claimed_by for r in replayed.context.get_map().routes},
            {r.route_id: r.claimed_by for r in original.context.get_map().routes},
        )
        self.assertEqual(replayed.context.action_log, original.context.action_log)

    def test_record_round_trips_through_json(self):
        original = _play_recorded(seed=77)
        record = record_of(original)
        restored = GameRecord.from_dict(json.loads(json.dumps(record.to_dict())))
        self.assertEqual(restored, record)
        replayed = replay_game(restored)
        self.assertEqual(replayed.context.scores, original.context.scores)


if __name__ == "__main__":
    unittest.main()
