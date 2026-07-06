import logging
from typing import List, Dict, Optional
from collections import Counter
from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, Pass,
    legal_keep_actions, legal_second_draw_actions, legal_turn_actions,
)
from ticket_to_ride.engine.legacy_adapter import LegacyBotAdapter
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.views import PlayerView

logger = logging.getLogger(__name__)


class Player:
    def __init__(self, player_id: str, interface, name: str, color: str):
        """Create a new player controlled by the provided interface."""
        self.player_id = player_id
        self.name = name
        self.color = color
        self.__train_hand: Counter[str] = Counter()
        self.exposed: Counter[str] = Counter()
        self.__tickets: List[DestinationTicket] = []
        self.trains_remaining: int = 45
        self.context: PlayerView
        self.__raw_interface = interface
        if not callable(getattr(interface, "act", None)):
            interface = LegacyBotAdapter(interface)
        self.__interface = interface
        self.__interface.set_player(self)
        self.has_longest_path: bool = False
        self.my_longest_path_length: int = 0
        self._game = None      # GameContext; set by attach()
        self._players = []     # full seat list; set by attach()

    def attach(self, game_context, players: 'List[Player]') -> None:
        """Bind the live GameContext (the engine's mutation channel) and the
        seat list. Views handed to bots never carry these."""
        self._game = game_context
        self._players = list(players)

    @property
    def game_context(self):
        """The live GameContext. Engine-internal: bots get PlayerViews."""
        return self._game

    # sets the view for the player
    def set_context(self, context: PlayerView, setup: bool = False):
        """Provide the player with the latest :class:`PlayerView`."""
        self.context = context
        if setup:
            deck = self._game.get_train_deck()
            for _ in range(4):
                self.__add_cards([deck.draw_face_down()], False)
            self.__draw_destination_tickets(min_keep=2)

    def take_turn(self) -> None:
        """Execute one turn: offer the legal menu, apply the chosen action."""
        begin_turn = getattr(self.__interface, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()
        completed = False
        try:
            action = self.__choose(legal_turn_actions(self), "turn")
            if isinstance(action, (DrawBlind, DrawFaceUp)):
                drew_locomotive = self.__apply_draw(action)
                if not drew_locomotive:
                    second = self.__choose(legal_second_draw_actions(self), "draw_second")
                    if not isinstance(second, Pass):
                        self.__apply_draw(second)
            elif isinstance(action, ClaimRoute):
                self.__apply_claim(action)
            elif isinstance(action, DrawTickets):
                self.__draw_destination_tickets()
            # Pass: nothing to do.

            # Re-evaluate tickets every turn, not only after own claims:
            # opponents' claims since last turn may have cut a ticket off, and
            # a shrinking train supply can make one impossible.
            self.check_ticket_completion()
            completed = True
        finally:
            end_turn = getattr(self.__interface, "end_turn", None)
            if callable(end_turn):
                end_turn(completed)

    def __choose(self, legal, decision: str, ticket_offer=None):
        """Build a fresh view, ask the interface, enforce legality."""
        view = PlayerView(
            self.player_id, self._game, self._players,
            decision=decision, ticket_offer=ticket_offer,
        )
        action = self.__interface.act(view, legal)
        if action not in legal:
            logger.warning(
                "Player %s chose illegal action %r for %s; using %r instead.",
                self.player_id, action, decision, legal[0],
            )
            action = legal[0]
        return action

    def __apply_draw(self, action) -> bool:
        """Apply a draw action; True if it was a face-up locomotive (which
        ends the drawing for this turn)."""
        deck = self._game.get_train_deck()
        if isinstance(action, DrawFaceUp):
            card = deck.draw_face_up(action.index)
            self.__add_cards([card], True)
            return card == "L"
        self.__add_cards([deck.draw_face_down()], False)
        return False

    def __apply_claim(self, action: ClaimRoute) -> None:
        route = self._game.get_map().route_by_id(action.route_id)
        needed = route.length - action.locomotives
        cards = ["L"] * action.locomotives
        if action.color != "L":
            cards.extend([action.color] * needed)
        self._spend_cards(cards)
        self.__claim_route(route)
        self.update_longest_path(route)

    def __draw_destination_tickets(self, min_keep: int = 1) -> bool:
        """Offer destination tickets; the interface picks a legal keep-set."""
        try:
            offer = self._game.get_ticket_deck().deal_unique(3)
        except Exception as e:
            logger.warning("Ticket draw failed for player %s: %s", self.player_id, e)
            return False
        if not offer:
            logger.info("No destination tickets available for %s.", self.player_id)
            return False

        legal = legal_keep_actions(len(offer), min_keep)
        choice = self.__choose(legal, "keep_tickets", ticket_offer=offer)
        kept = [offer[i] for i in choice.indices]
        self.__tickets.extend(kept)
        returned = [t for i, t in enumerate(offer) if i not in choice.indices]
        self._game.get_ticket_deck().return_tickets(returned)
        return True

    # Helpers
    def get_no_locomotives(self):
        """Return a copy of the player's hand without locomotives."""
        no_locomotives = self.__train_hand.copy()
        if "L" in no_locomotives.keys():
            no_locomotives.pop("L")
        return no_locomotives

    def get_context(self):
        """Expose the player's current context."""
        return self.context

    def get_interface(self):
        """Return the interface this player was constructed with (the
        original object, not the act() adapter it may be wrapped in)."""
        return self.__raw_interface

    

    def __add_cards(self, cards: List[str], exposed: bool) -> None:
        """Add drawn cards to the player's hand."""
        self.__train_hand.update(cards)
        if exposed:
            self.exposed.update(cards)

    def _spend_cards(self, cards: List[str]) -> None:
        """Spend cards from the player's hand and discard them."""
        self.__train_hand.subtract(cards)
        self._game.get_train_deck().discard(cards)
        self.exposed.subtract(cards)
        # clamp in place: views hold a live reference to this Counter
        for color, count in list(self.exposed.items()):
            if count < 0:
                self.exposed[color] = 0

    def __claim_route(self, route: Route) -> None:
        """Mark a route as claimed and update train count."""
        self.trains_remaining -= route.length
        self._game.get_map().claim_route(route, self.player_id)

    def __hand_counts(self) -> 'Counter[str]':
        """Return a copy of the player's full hand counts."""
        return self.__train_hand.copy()

    def get_exposed(self) -> 'Counter[str]':
        """Public information about cards drawn face up."""
        return self.exposed
    
    def get_hand(self) -> 'Counter[str]':
        """Return the player's current hand."""
        return self.__train_hand

    def get_card_count(self) -> int:
        """Total number of train cards in hand."""
        return sum(self.__train_hand.values())
    
    def get_tickets(self) -> List[DestinationTicket]:
        """Return the player's destination tickets."""
        return self.__tickets

    def get_affordable_routes(self) -> 'List[tuple[Route, int]]':
        """List routes this player can currently afford to claim."""
        if not self.__train_hand.total(): # type: ignore
            return []
        locomotives = self.__train_hand.get("L", 0)
        colors = self.get_no_locomotives()
        most_common_num = max(colors.values(), default=0)
        affordable_routes = []

        for r in self._game.get_map().get_available_routes(self.player_id):
            if r.length > self.trains_remaining:
                continue
            for n in range(locomotives + 1):
                # if the player has enough of the color in hand or if the color is gray and the player has enough of their most common color in hand
                needed = r.length - n
                if colors.get(r.color, 0) >= needed or (r.color == "X" and most_common_num >= needed):
                    affordable_routes.append((r, n))
                    break
        return affordable_routes
    
    def update_longest_path(self, new_route: Route):
        """Notify the map that this player claimed a new route."""
        self._game.get_map().update_longest_path(self.player_id, new_route)
        self.my_longest_path_length = self._game.get_map().longest_paths[self.player_id]
        self.has_longest_path = (self._game.get_map().longest_path_holder == self.player_id)

    def get_culled_map(self):
        """This player's contracted view of the board (see MapGraph.culled_map_for).

        Own claims merge cities into single nodes and only routes this player
        could still claim survive - so shortest paths over it answer "what
        would it cost to connect X and Y from here?".
        """
        return self._game.get_map().culled_map_for(self.player_id)

    def is_connected(self, city1: str, city2: str) -> bool:
        """True if this player's claimed routes already join the two cities."""
        return self.get_culled_map().connected(city1, city2)

    def connection_cost(self, city1: str, city2: str) -> 'int | None':
        """Fewest trains needed to connect two cities from this player's
        position (0 = already connected, None = impossible)."""
        return self.get_culled_map().cheapest_connection(city1, city2)

    def check_ticket_completion(self):
        """Mark tickets completed or impossible from this player's culled map.

        Uses the exact same queries exposed to bots (connection_cost), so a
        bot can predict precisely how the engine will judge its tickets.
        """
        culled = self.get_culled_map()
        for ticket in self.__tickets:
            if ticket.is_completed or ticket.is_impossible:
                continue
            cost = culled.cheapest_connection(ticket.city1, ticket.city2)
            if cost == 0:
                ticket.is_completed = True
            elif cost is None or cost > self.trains_remaining:
                ticket.is_impossible = True

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(id={self.player_id}, trains={self.trains_remaining}, "
                f"hand={dict(self.__train_hand)}, tickets={self.__tickets})")


