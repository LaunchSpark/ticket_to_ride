from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.decks import TrainCardDeck, TicketDeck

from collections import Counter
from typing import Dict, List



class GameContext:
    def __init__(self, player_ids):
        """Holds shared state used throughout the gameplay loop."""
        print("Initializing GameContext...")
        self.map_graph = MapGraph(player_count=len(player_ids))
        self.train_deck = TrainCardDeck()
        self.ticket_deck = TicketDeck()
        self.turn_num = 0
        # initialize score dictionary for all players
        # each player starts with a score of 0
        self.scores = {p: 0 for p in player_ids}


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




