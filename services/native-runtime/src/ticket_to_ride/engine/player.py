import logging
from typing import List, Dict, Optional
from collections import Counter
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
        self.__interface = interface
        self.__interface.set_player(self)
        self.has_longest_path: bool = False
        self.my_longest_path_length: int = 0

    # sets the view for the player
    def set_context(self, context: PlayerView, setup: bool = False):
        """Provide the player with the latest :class:`PlayerView`."""
        self.context = context
        if setup:
            for i in range(0, 2):
                self.__draw_train_cards([-1] * 2)
            self.__draw_destination_tickets()
            if len(self.__tickets) < 2:
                self.__draw_destination_tickets()

    #prompts interface for turn option
    def take_turn(self, fault_flags: Dict[str, bool]) -> None:
        """Execute a single iteration of the gameplay loop for this player.

        Runs as a retry loop: an action that turns out to be unavailable sets
        its fault flag and re-prompts the interface, so begin_turn/end_turn
        fire exactly once per turn no matter how many retries happen.
        """
        begin_turn = getattr(self.__interface, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()
        completed = False
        try:
            while True:
                turn_choice = self.__interface.choose_turn_action()

                # Check if there are enough cards in the deck to draw; if not, shuffle in the discard and check again.
                # If there are still less than 2 cards in the deck, force the player to claim a route if they can afford one, or to pass the turn if they can't
                if len(self.context.train_deck) < 2:
                    self.context.train_deck._reshuffle_discard()
                    if len(self.context.train_deck) < 2:
                        fault_flags['draw_train'] = True

                if turn_choice == 1 and not fault_flags['draw_train']: ## Draw Cards
                    self.__draw_train_cards()
                    break

                if turn_choice in (1, 2): ## Claim Route (choice 1 is forced here when the deck is dry)
                    if fault_flags['claim_route']:
                        # already failed to claim once this turn
                        if not fault_flags['draw_train']:
                            self.__draw_train_cards([-1] * 2)
                        break  # both faults: nothing left to do but pass
                    if not self.get_affordable_routes():
                        fault_flags['claim_route'] = True
                        logger.info("%s cannot currently afford any routes. Trying something else.", self.name)
                        continue
                    route = self.__claim_available_route(fault_flags['draw_train'])
                    self.update_longest_path(route)
                    break

                if turn_choice == 3: ## Draw Destination tickets
                    if fault_flags['draw_destination']:
                        self.__draw_train_cards([-1] * 2)
                        break
                    if len(self.context.ticket_deck) < 3:
                        fault_flags['draw_destination'] = True
                        logger.info("There aren't enough destination tickets left for %s. Trying something else.", self.name)
                        continue
                    if not self.__draw_destination_tickets():
                        fault_flags['draw_destination'] = True
                        logger.info("%s could not draw destination tickets. Trying something else.", self.player_id)
                        continue
                    break

                logger.warning("Invalid action choice '%s' by player %s.", turn_choice, self.player_id)
                break

            # Re-evaluate tickets every turn, not only after own claims:
            # opponents' claims since last turn may have cut a ticket off, and
            # a shrinking train supply can make one impossible.
            self.check_ticket_completion()
            completed = True
        finally:
            end_turn = getattr(self.__interface, "end_turn", None)
            if callable(end_turn):
                end_turn(completed)

    # handlers for each option
    def __draw_train_cards(self, draws: Optional[List[int]] = None) -> str:
        """Internal helper for drawing train cards.

        Each pick is validated against the market as it exists at draw time
        (the first draw refills the market before the second happens). A
        face-up locomotive may only be taken as the sole card of the turn:
        taking one first ends the draw, and a second pick that lands on a
        locomotive becomes a face-down draw instead.
        """
        draw_choices = [self.__interface.choose_draw_train_action() for _ in range(2)] if draws is None else draws
        train_deck = self.context.train_deck

        for position, choice in enumerate(draw_choices):
            if choice >= 0:
                face_up = train_deck.get_face_up()
                if choice >= len(face_up):
                    logger.warning("Invalid face-up index '%s' by player %s.", choice, self.player_id)
                    return 'invalid'
                if face_up[choice] == 'L':
                    if position == 0:
                        card = train_deck.draw_face_up(choice)
                        self.__add_cards([card], True)
                        return 'success'
                    choice = -1  # locomotives can't be the second pick; draw blind instead
                else:
                    card = train_deck.draw_face_up(choice)
                    self.__add_cards([card], True)
                    continue

            if choice == -1:
                try:
                    card = train_deck.draw_face_down()
                    self.__add_cards([card], False)
                except Exception as e:
                    logger.warning("Face-down draw failed for player %s: %s", self.player_id, e)
                    return 'invalid'
            else:
                logger.warning("Invalid draw choice '%s' by player %s.", choice, self.player_id)
                return 'invalid'

        return 'success'
    
    def __claim_available_route(self, l_fault: Optional[bool]) -> Route:
        """Spend cards and claim a route chosen by the interface."""
        affordable_routes = self.get_affordable_routes()
        route, l_count = self.__interface.choose_route_to_claim(affordable_routes)
        if l_count > self.__train_hand.get("L", 0):
            logger.warning("Player %s doesn't have %s locomotives to spend; try again.", self.name, l_count)
            if not l_fault:
                return self.__claim_available_route(True)
            l_count = 0
        affordable_routes = [r for (r, l) in affordable_routes if l <= l_count]
        if route not in affordable_routes:
            logger.warning(
                "Player %s can't afford route %s this turn; we've chosen %s for them instead.",
                self.name, route, affordable_routes[0],
            )
            route = affordable_routes[0]
        cards_to_spend = []
        if l_count >= route.length:
            l_count = route.length
        else:
            needed = route.length - l_count
            if route.color == "X":
                color_options = [c for c in self.__train_hand.keys() if self.__train_hand.get(c, 0) >= needed and c != 'L']
                chosen_color = self.__interface.choose_color_to_spend(route, color_options) if color_options else None
                # honor the chosen color if they actually have enough of it; otherwise spend the one they have the most of
                if chosen_color is not None and self.__train_hand.get(chosen_color, 0) >= needed:
                    color_to_spend = chosen_color
                else:
                    color_to_spend = self.get_no_locomotives().most_common(1)[0][0]
            else:
                color_to_spend = route.color
            cards_to_spend.extend([color_to_spend] * needed)
        cards_to_spend.extend(["L"] * l_count)
        self._spend_cards(cards_to_spend)
        self.__claim_route(route)
        return route

    def __draw_destination_tickets(self) -> bool:
        """Offer destination tickets and keep the chosen ones."""
        try:
            offer = self.context.ticket_deck.deal_unique(3)
        except Exception as e:
            logger.warning("Ticket draw failed for player %s: %s", self.player_id, e)
            return False

        if not offer:
            logger.info("No destination tickets available for %s.", self.player_id)
            return False

        kept = self.__interface.select_ticket_offer(offer)
        if not kept:
            logger.info("%s kept no tickets from offer.", self.player_id)
            return False

        self.__tickets.extend(kept)
        returned = [t for t in offer if t not in kept]
        self.context.ticket_deck.return_tickets(returned)
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
        """Return the controlling interface for this player."""
        return self.__interface

    

    def __add_cards(self, cards: List[str], exposed: bool) -> None:
        """Add drawn cards to the player's hand."""
        self.__train_hand.update(cards)
        if exposed:
            self.exposed.update(cards)

    def _spend_cards(self, cards: List[str]) -> None:
        """Spend cards from the player's hand and discard them."""
        self.__train_hand.subtract(cards)
        self.context.train_deck.discard(cards)
        self.exposed.subtract(cards)
        # clamp in place: views hold a live reference to this Counter
        for color, count in list(self.exposed.items()):
            if count < 0:
                self.exposed[color] = 0

    def __claim_route(self, route: Route) -> None:
        """Mark a route as claimed and update train count."""
        self.trains_remaining -= route.length
        self.context.map.claim_route(route, self.player_id)

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

        for r in self.context.map.get_available_routes(self.player_id):
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
        self.context.map.update_longest_path(self.player_id, new_route)
        self.my_longest_path_length = self.context.map.longest_paths[self.player_id]
        self.has_longest_path = (self.context.map.longest_path_holder == self.player_id)

    def get_culled_map(self):
        """This player's contracted view of the board (see MapGraph.culled_map_for).

        Own claims merge cities into single nodes and only routes this player
        could still claim survive - so shortest paths over it answer "what
        would it cost to connect X and Y from here?".
        """
        return self.context.map.culled_map_for(self.player_id)

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


