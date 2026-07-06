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
from typing import Dict, List, Optional, Tuple
from typing import TYPE_CHECKING

from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import MapGraph, Route, _route_claimable_by, contract_map
from ticket_to_ride.engine.state.decks import DestinationTicket

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
    """One seat's view of the game: plain data plus pure queries.

    Everything here is either a scalar, a copy, or a pure function of the
    captured claim state — there is nothing a bot can call to mutate the
    game. The engine builds a fresh view for every decision it asks a bot
    to make, so the data is always current as of that decision.

    `decision` says which decision this view was built for ("turn",
    "draw_second", or "keep_tickets"); `ticket_offer` carries the offered
    DestinationTickets during a "keep_tickets" decision.
    """

    def __init__(self, player_id: str, context: GameContext, players: List,
                 decision: str = "turn",
                 ticket_offer: 'Optional[List[DestinationTicket]]' = None):
        player = next(p for p in players if p.player_id == player_id)
        map_graph = context.get_map()
        train_deck = context.get_train_deck()

        self.player_id: str = player_id
        self.decision: str = decision
        self.ticket_offer = ticket_offer
        self.map_name: str = map_graph.map_name
        self.player_count: int = map_graph.player_count
        self.turn_number: int = context.turn_num
        self.score: int = context.get_score(player_id)
        self.face_up_cards: List[str] = train_deck.get_face_up()
        self.train_cards_in_deck: int = len(train_deck)
        self.tickets_in_deck: int = len(context.get_ticket_deck())
        self.hand: 'Counter[str]' = Counter(player.get_hand())
        self.trains_remaining: int = player.trains_remaining
        self.tickets: List[DestinationTicket] = list(player.get_tickets())
        self.routes: List[Route] = list(map_graph.routes)
        self.claimed_by: Dict[str, str] = {
            route.route_id: route.claimed_by
            for route in self.routes if route.claimed_by is not None
        }

        self.opponents = [
            OpponentInfo(
                player_id=p.player_id,
                exposed_hand=Counter(p.get_exposed()),
                num_cards_in_hand=p.get_card_count(),
                remaining_trains=p.trains_remaining,
                score=context.get_score(p.player_id),
                destination_ticket_count=len(p.get_tickets()),
            ) for p in players if p.player_id != player_id
        ]

    def route_by_id(self, route_id: str) -> Route:
        index = getattr(self, "_routes_by_id", None)
        if index is None:
            index = {route.route_id: route for route in self.routes}
            self._routes_by_id = index
        return index[route_id]

    def culled_map(self):
        """This player's contracted board (see contract_map), from the
        claims as captured in this view."""
        return contract_map(self.routes, self.player_count, self.claimed_by, self.player_id)

    def is_connected(self, city1: str, city2: str) -> bool:
        return self.culled_map().connected(city1, city2)

    def connection_cost(self, city1: str, city2: str) -> 'int | None':
        return self.culled_map().cheapest_connection(city1, city2)

    def affordable_routes(self) -> 'List[Tuple[Route, int]]':
        """(route, locomotives) pairs this player could claim right now —
        the same algorithm as Player.get_affordable_routes, computed purely
        from this view's data."""
        if not self.hand.total():
            return []
        locomotives = self.hand.get("L", 0)
        colors = Counter({c: n for c, n in self.hand.items() if c != "L" and n > 0})
        most_common = max(colors.values(), default=0)

        siblings_by_key: 'Dict[tuple, List[Route]]' = {}
        for route in self.routes:
            siblings_by_key.setdefault(route.sibling_group_key(), []).append(route)
        claim_of = lambda route: self.claimed_by.get(route.route_id)

        affordable = []
        for route in self.routes:
            siblings = [s for s in siblings_by_key[route.sibling_group_key()] if s is not route]
            if not _route_claimable_by(route, siblings, claim_of, self.player_id, self.player_count):
                continue
            if route.length > self.trains_remaining:
                continue
            for n in range(locomotives + 1):
                needed = route.length - n
                if colors.get(route.color, 0) >= needed or (route.color == "X" and most_common >= needed):
                    affordable.append((route, n))
                    break
        return affordable


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
