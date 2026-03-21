from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import Counter
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import MapGraph, Route
from ticket_to_ride.engine.state.decks import TicketDeck, TrainCardDeck, DestinationTicket
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ticket_to_ride.engine.player import Player

@dataclass
class OpponentInfo:
    player_id: str
    exposed_hand: 'Counter[str]'
    num_cards_in_hand: int
    remaining_trains: int
    score: int
    destination_ticket_count: int

class PlayerContext:
    def __init__(self, player_id: str, context: GameContext, players: List):
        """Snapshot of public information passed to a :class:`Player`."""
        player = next((player for player in players if player.player_id == player_id), None)
        self.player_id: str = player_id
        self.map: MapGraph = context.get_map()
        self.train_deck: TrainCardDeck = context.get_train_deck()
        self.ticket_deck: TicketDeck = context.get_ticket_deck()
        self.face_up_cards: List[str] = context.get_train_deck().get_face_up()
        self.turn_number: int = context.turn_num
        self.score: int = context.get_score(player_id)

        self.opponents = [
            OpponentInfo(
                player_id = p.player_id,
                exposed_hand = p.get_exposed(),
                num_cards_in_hand = p.get_card_count(),
                remaining_trains = p.trains_remaining,
                score = context.get_score(p.player_id),
                destination_ticket_count = len(p.get_tickets())
            ) for p in players if p.player_id != self.player_id
        ]




