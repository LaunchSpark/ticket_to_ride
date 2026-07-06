from __future__ import annotations

import unittest

from external.bots.example_bot import ExampleBot
from ticket_to_ride.runtime.cli import BootstrapRandomBot

from notebook_harness.game_runner import initialize_game


class ExampleBotTests(unittest.TestCase):
    def test_example_bot_plays_a_full_game_without_faulting(self) -> None:
        harness_game = initialize_game([ExampleBot(), BootstrapRandomBot()])

        harness_game.play()

        self.assertGreater(harness_game.snapshot_count(), 0)

        example_player = harness_game.players[0]
        # The initial offer logic keeps at least the best pair.
        self.assertGreaterEqual(len(example_player.get_tickets()), 2)
        # A planning bot that survives a whole game should have claimed
        # something toward its tickets.
        claimed = harness_game.game.context.get_map().get_claimed_routes("bot_0")
        self.assertGreater(len(claimed), 0)

    def test_example_bot_initial_offer_keeps_a_ticket_pair(self) -> None:
        from ticket_to_ride.engine.state.views import PlayerView

        example_bot = ExampleBot()
        harness_game = initialize_game([example_bot, BootstrapRandomBot()])
        game = harness_game.game
        player = game.players[0]
        # Tickets are normally dealt when play() starts; wire the context up
        # manually so the offer can be driven directly.
        player.set_context(PlayerView(player.player_id, game.context, game.players), False)

        offer = player.context.ticket_deck.deal_unique(3)
        kept = example_bot.select_ticket_offer(offer)

        # Fresh board: everything is viable, so the pair logic keeps the best
        # two (plus optionally a cheap third).
        self.assertGreaterEqual(len(kept), 2)
        self.assertLessEqual(len(kept), 3)
        for ticket in kept:
            self.assertIn(ticket, offer)


if __name__ == "__main__":
    unittest.main()
