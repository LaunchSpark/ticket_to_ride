import logging
import random

from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.decks import TrainCardDeck, TicketDeck

from collections import Counter
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class GameContext:
    def __init__(self, player_ids, map_name: Optional[str] = None, seed: Optional[int] = None):
        """Holds shared state used throughout the gameplay loop.

        All engine randomness (deck shuffles, market refills, ticket deals)
        flows from `self.rng`, so a (seed, action sequence) pair replays to
        an identical game.
        """
        logger.info("Initializing GameContext...")
        self.seed = seed if seed is not None else random.randrange(2**32)
        self.rng = random.Random(self.seed)
        self.map_graph = MapGraph(player_count=len(player_ids), map_name=map_name)
        self.train_deck = TrainCardDeck(rng=self.rng)
        self.ticket_deck = TicketDeck(rng=self.rng)
        self.turn_num = 0
        # initialize score dictionary for all players
        # each player starts with a score of 0
        self.scores = {p: 0 for p in player_ids}
        # Every action a player chose, in play order: (player_id, Action).
        # With self.seed this replays to an identical game (engine/replay.py).
        self.action_log: List[tuple] = []


    def set_score(self, player_id, score):
        """Update a player's score in the context."""
        self.scores[player_id] = score

    def get_score(self, player_id: str):
        """Retrieve the current score for the given player."""
        return self.scores[player_id]

    def get_map(self) -> MapGraph:
        """Return the shared game map."""
        return self.map_graph

    def get_train_deck(self) -> TrainCardDeck:
        """Return the deck of train cards used during play."""
        return self.train_deck

    def get_ticket_deck(self) -> TicketDeck:
        """Return the deck of destination tickets."""
        return self.ticket_deck




