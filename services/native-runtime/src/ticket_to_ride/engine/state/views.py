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

from ticket_to_ride.engine.actions import affordable_route_options
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import MapGraph, Route, _UnionFind, contract_map
from ticket_to_ride.engine.state.decks import DestinationTicket, TrainCardDeck

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
        self.discard_pile: 'Counter[str]' = Counter(train_deck.get_discard_pile())
        self.train_cards_in_deck: int = len(train_deck)
        self.tickets_in_deck: int = len(context.get_ticket_deck())
        self.hand: 'Counter[str]' = Counter(player.get_hand())
        self.trains_remaining: int = player.trains_remaining
        self.tickets: List[DestinationTicket] = list(player.get_tickets())
        self.routes: List[Route] = list(map_graph.routes)
        self.claimed_by: Dict[str, str] = map_graph.claim_snapshot()

        # Longest-path standings, straight from the engine's incremental
        # tracking (public information: claims are visible to everyone).
        # Holder is "" until someone claims a route.
        self.longest_path_holder: str = map_graph.longest_path_holder
        self.longest_paths: Dict[str, int] = {
            p.player_id: map_graph.longest_paths.get(p.player_id, 0)
            for p in players
        }

        # Cache plumbing (private, not part of the bot-facing API): the
        # claim version this view was built at, the map's immutable sibling
        # index, and the live map itself so culled_map() can reuse the
        # engine's claim-versioned cache while the snapshot is still current.
        self._claim_version: int = map_graph.claim_version
        self._siblings_by_key = map_graph.sibling_index
        self._map_graph: MapGraph = map_graph
        self._culled_map = None
        self._unknown_pool: 'Optional[Counter[str]]' = None
        self._ticket_costs: 'Optional[List[int | None]]' = None
        self._claim_components: 'Dict[str, List[List[str]]]' = {}

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
        claims as captured in this view.

        Computed once per view and reused: claims can't change during the
        decision a view is built for, so is_connected/connection_cost calls
        all share one CulledMap. While the live map hasn't advanced past
        this view's snapshot (always true during live play), the engine's
        claim-versioned cache is reused directly; a view held across later
        claims falls back to rebuilding from its own snapshot.
        """
        if self._culled_map is None:
            if self._map_graph.claim_version == self._claim_version:
                self._culled_map = self._map_graph.culled_map_for(self.player_id)
            else:
                self._culled_map = contract_map(
                    self.routes, self.player_count, self.claimed_by, self.player_id,
                    siblings_by_key=self._siblings_by_key,
                )
        return self._culled_map

    def ticket_costs(self) -> 'List[int | None]':
        """Fewest trains still needed to finish each ticket, aligned with
        `self.tickets` (0 = connected, None = cut off by other players).

        The exact query the engine runs when judging tickets at end of turn
        (Player.check_ticket_completion): it marks a ticket completed at
        cost 0 and impossible when the cost is None or exceeds
        trains_remaining — so a bot can predict that judgment precisely.
        Computed from this view's culled map and memoized.
        """
        if self._ticket_costs is None:
            culled = self.culled_map()
            self._ticket_costs = [
                culled.cheapest_connection(ticket.city1, ticket.city2)
                for ticket in self.tickets
            ]
        return list(self._ticket_costs)

    def claim_components(self, player_id: 'Optional[str]' = None) -> 'List[List[str]]':
        """The city networks a player has merged with their claims, as
        captured in this view: one sorted city list per connected component
        (singletons omitted), components ordered by first city.

        Claims are public, so any seat may be queried — pass an opponent's
        id to see which of their cities are already joined (the engine
        tracks this incrementally per claim; here it is derived from the
        view's claim snapshot and memoized). Defaults to this view's player.
        """
        player_id = player_id if player_id is not None else self.player_id
        cached = self._claim_components.get(player_id)
        if cached is None:
            components = _UnionFind()
            claimed_cities = set()
            for route in self.routes:
                if self.claimed_by.get(route.route_id) == player_id:
                    components.union(route.city1, route.city2)
                    claimed_cities.update((route.city1, route.city2))
            members_by_root: 'Dict[str, List[str]]' = {}
            for city in sorted(claimed_cities):
                members_by_root.setdefault(components.find(city), []).append(city)
            cached = sorted(members_by_root.values())
            self._claim_components[player_id] = cached
        return [list(component) for component in cached]

    def is_connected(self, city1: str, city2: str) -> bool:
        return self.culled_map().connected(city1, city2)

    def connection_cost(self, city1: str, city2: str) -> 'int | None':
        return self.culled_map().cheapest_connection(city1, city2)

    def unknown_pool(self) -> 'Counter[str]':
        """Color counts of every card this player cannot see: the draw pile
        plus opponents' hidden (face-down-drawn) cards. Computed purely from
        public information: the full 110-card composition minus the face-up
        market, the discard pile, opponents' exposed cards, and this
        player's own hand."""
        if self._unknown_pool is None:
            pool = Counter(TrainCardDeck.COLOR_COUNTS)
            pool.subtract(self.face_up_cards)
            pool.subtract(self.discard_pile)
            pool.subtract(self.hand)
            for opponent in self.opponents:
                pool.subtract(opponent.exposed_hand)
            self._unknown_pool = +pool  # drop zero/negative entries
        return Counter(self._unknown_pool)  # callers own their copy

    def draw_odds(self) -> Dict[str, float]:
        """Probability the next blind draw is each color, from this player's
        public information (the unknown pool). Empty dict if nothing is
        drawable."""
        pool = self.unknown_pool()
        total = pool.total()
        if not total:
            return {}
        return {color: count / total for color, count in sorted(pool.items())}

    def affordable_routes(self) -> 'List[Tuple[Route, int]]':
        """(route, locomotives) pairs this player could claim right now —
        the same algorithm as Player.get_affordable_routes, computed purely
        from this view's data."""
        return affordable_route_options(
            self.routes,
            self._siblings_by_key,
            lambda route: self.claimed_by.get(route.route_id),
            self.player_id,
            self.player_count,
            self.hand,
            self.trains_remaining,
        )


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

    @property
    def longest_paths(self) -> Dict[str, int]:
        """Longest continuous path per player who has claimed a route, from
        the engine's incremental tracking."""
        return dict(self.map.longest_paths)

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

    def deck_composition(self) -> 'Counter[str]':
        """True color counts of the face-down draw pile (spectator only)."""
        return self._context.get_train_deck().deck_composition()


# Alias from before the snapshot -> view rename.
PlayerContext = PlayerView
