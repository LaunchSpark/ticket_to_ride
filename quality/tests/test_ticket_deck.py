from __future__ import annotations

import random
import unittest

from ticket_to_ride.engine.state.decks import (
    DestinationTicket, TicketDeck, resolve_tickets_path,
)


def _tickets(n, prefix="City"):
    return [DestinationTicket(f"{prefix}{i}A", f"{prefix}{i}B", i + 5) for i in range(n)]


class TicketDeckSourceTests(unittest.TestCase):
    def test_default_still_loads_the_classic_deck(self):
        self.assertGreater(len(TicketDeck()), 0)

    def test_csv_path_source_still_works(self):
        deck = TicketDeck(resolve_tickets_path("europe"))
        self.assertEqual(len(deck), 46)

    def test_in_memory_ticket_source(self):
        deck = TicketDeck(_tickets(5), rng=random.Random(1))
        self.assertEqual(len(deck), 5)
        dealt = deck.deal_unique(5)
        self.assertEqual({t.value for t in dealt}, {5, 6, 7, 8, 9})

    def test_empty_deck_hydrates_later(self):
        deck = TicketDeck(None, rng=random.Random(2))
        self.assertEqual(len(deck), 0)
        self.assertEqual(deck.deal_unique(3), [])

        deck.add_tickets(_tickets(4))
        self.assertEqual(len(deck), 4)
        self.assertEqual(len(deck.deal_unique(3)), 3)

        # a second hydration mid-life shuffles in with what remains
        deck.add_tickets(_tickets(2, prefix="New"))
        self.assertEqual(len(deck), 3)

    def test_hydration_order_is_seed_deterministic(self):
        a = TicketDeck(None, rng=random.Random(7))
        b = TicketDeck(None, rng=random.Random(7))
        for deck in (a, b):
            deck.add_tickets(_tickets(8))
        self.assertEqual(
            [(t.city1, t.city2) for t in a.deal_unique(8)],
            [(t.city1, t.city2) for t in b.deal_unique(8)],
        )


if __name__ == "__main__":
    unittest.main()
