"""Read-through views of live game state.

These are *views*, not snapshots: each one holds references to the live game
objects and reflects the current state whenever it is queried. None of them
need to be rebuilt as the game advances — the engine refreshes PlayerView
each turn only to re-capture its per-turn scalars (score, turn number, the
market as of turn start), while the global views are built once and stay
valid for the whole game.
"""
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List
from typing import TYPE_CHECKING

from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.decks import TicketDeck, TrainCardDeck, DestinationTicket

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


class PlayerView:
    def __init__(self, player_id: str, context: GameContext, players: List):
        """One seat's view of the shared game state.

        The map and decks are the live objects, so claims and market changes
        show through immediately; scalar fields such as `score`,
        `turn_number`, and `face_up_cards` are captured when the view is
        built, which the engine does at the start of every turn.
        """
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


@dataclass
class PlayerPublicInfo:
    """One player's publicly observable state, as reported by GlobalPublicView."""

    player_id: str
    name: str
    color: str
    exposed_hand: 'Counter[str]'
    num_cards_in_hand: int
    remaining_trains: int
    score: int
    destination_ticket_count: int
    has_longest_path: bool


class GlobalPublicView:
    """Everything any observer at the table may see.

    Build it once per game and query it whenever needed — every accessor
    reads the live game state at call time.
    """

    def __init__(self, context: GameContext, players: 'List[Player]'):
        self._context = context
        self._players = list(players)

    @property
    def map(self) -> MapGraph:
        return self._context.get_map()

    @property
    def face_up_cards(self) -> List[str]:
        return self._context.get_train_deck().get_face_up()

    @property
    def train_cards_in_deck(self) -> int:
        return len(self._context.get_train_deck())

    @property
    def tickets_in_deck(self) -> int:
        return len(self._context.get_ticket_deck())

    @property
    def turn_number(self) -> int:
        return self._context.turn_num

    @property
    def scores(self) -> Dict[str, int]:
        return dict(self._context.scores)

    @property
    def longest_path_holder(self) -> str:
        return self.map.longest_path_holder

    def players(self) -> List[PlayerPublicInfo]:
        return [
            PlayerPublicInfo(
                player_id=p.player_id,
                name=p.name,
                color=p.color,
                exposed_hand=Counter(p.get_exposed()),
                num_cards_in_hand=p.get_card_count(),
                remaining_trains=p.trains_remaining,
                score=self._context.get_score(p.player_id),
                destination_ticket_count=len(p.get_tickets()),
                has_longest_path=p.has_longest_path,
            )
            for p in self._players
        ]


class GlobalPrivateView(GlobalPublicView):
    """The omniscient extension of the public view: full hands and tickets.

    For notebooks and analysis only — never hand this to a bot.
    """

    def hands(self) -> 'Dict[str, Counter[str]]':
        return {p.player_id: Counter(p.get_hand()) for p in self._players}

    def tickets(self) -> Dict[str, List[DestinationTicket]]:
        return {p.player_id: list(p.get_tickets()) for p in self._players}


# Alias from before the snapshot -> view rename.
PlayerContext = PlayerView
