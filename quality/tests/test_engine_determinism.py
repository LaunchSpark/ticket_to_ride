import random
import unittest

from ticket_to_ride.engine.state.decks import TicketDeck, TrainCardDeck
from ticket_to_ride.engine.state.game_context import GameContext


class SeededDecksTests(unittest.TestCase):
    def test_same_seed_same_train_deck_order(self):
        a = TrainCardDeck(rng=random.Random(7))
        b = TrainCardDeck(rng=random.Random(7))
        self.assertEqual(a.get_face_up(), b.get_face_up())
        self.assertEqual(
            [a.draw_face_down() for _ in range(20)],
            [b.draw_face_down() for _ in range(20)],
        )

    def test_reshuffle_uses_injected_rng(self):
        a = TrainCardDeck(rng=random.Random(3))
        b = TrainCardDeck(rng=random.Random(3))
        for deck in (a, b):
            deck.discard([deck.draw_face_down() for _ in range(10)])
            deck._reshuffle_discard()
        self.assertEqual(
            [a.draw_face_down() for _ in range(10)],
            [b.draw_face_down() for _ in range(10)],
        )

    def test_draw_face_up_with_exhausted_piles_leaves_market_short(self):
        deck = TrainCardDeck(rng=random.Random(5))
        while len(deck):
            deck.draw_face_down()
        # both piles empty: taking a face-up card must not hang, and the
        # market just stays one card short
        before = len(deck.get_face_up())
        deck.draw_face_up(0)
        self.assertEqual(len(deck.get_face_up()), before - 1)

    def test_same_seed_same_ticket_order(self):
        a = TicketDeck(rng=random.Random(7))
        b = TicketDeck(rng=random.Random(7))
        self.assertEqual(
            [(t.city1, t.city2) for t in a.deal_unique(5)],
            [(t.city1, t.city2) for t in b.deal_unique(5)],
        )


class SeededContextTests(unittest.TestCase):
    def test_context_seed_controls_decks(self):
        a = GameContext(["p1", "p2"], seed=99)
        b = GameContext(["p1", "p2"], seed=99)
        self.assertEqual(a.seed, 99)
        self.assertEqual(a.get_train_deck().get_face_up(), b.get_train_deck().get_face_up())
        self.assertEqual(
            [(t.city1, t.city2) for t in a.get_ticket_deck().deal_unique(3)],
            [(t.city1, t.city2) for t in b.get_ticket_deck().deal_unique(3)],
        )

    def test_unseeded_context_records_generated_seed(self):
        context = GameContext(["p1"])
        self.assertIsInstance(context.seed, int)


class HarnessSeedTests(unittest.TestCase):
    def test_initialize_game_forwards_seed(self):
        from notebook_harness.game_runner import initialize_game

        class StubBot:
            def set_player(self, player):
                self.player = player

        a = initialize_game([StubBot(), StubBot()], seed=1234)
        b = initialize_game([StubBot(), StubBot()], seed=1234)
        self.assertEqual(a.game.context.seed, 1234)
        self.assertEqual(
            a.game.context.get_train_deck().get_face_up(),
            b.game.context.get_train_deck().get_face_up(),
        )


if __name__ == "__main__":
    unittest.main()
