from copy import deepcopy
from typing import List, Dict, Optional
from collections import Counter
import weakref
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.player_context import PlayerContext




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
        self.context: PlayerContext
        self.__interface = interface
        self.__interface.set_player(self)
        self.has_longest_path: bool = False
        self.my_longest_path_length: int

    # sets the context for the player
    def set_context(self, context: PlayerContext, setup: bool = False):
        """Provide the player with the latest :class:`PlayerContext`."""
        self.context = context
        if setup:
            for i in range(0, 2):
                self.__draw_train_cards([-1] * 2)
            self.__draw_destination_tickets()
            if len(self.__tickets) < 2:
                self.__draw_destination_tickets()

    #prompts interface for turn option
    def take_turn(self, fault_flags: Dict[str, bool]) -> None:
        """Execute a single iteration of the gameplay loop for this player."""
        begin_turn = getattr(self.__interface, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()
        completed = False
        try:
            turn_choice = self.__interface.choose_turn_action()
            
            # Check if there are enough cards in the deck to draw; if not, shuffle in the discard and check again. 
            # If there are still less than 2 cards in the deck, force the player to claim a route if they can afford one, or to pass the turn if they can't
            if len(self.context.train_deck) < 2:
                self.context.train_deck._reshuffle_discard()
                if len(self.context.train_deck) < 2:
                    fault_flags['draw_train'] = True

            if turn_choice == 1: ## Draw Cards
                # if there is a fault flag, force players to claim routes if possible
                if not fault_flags['draw_train']:
                    self.__prompt_draw_train()
                else:
                    self.__prompt_claim_route(fault_flags)

            elif turn_choice == 2: ## Claim Route
                self.__prompt_claim_route(fault_flags)

            elif turn_choice == 3: ## Draw Destination tickets
                self.__prompt_draw_ticket(fault_flags)

            else:
                print(f"Invalid action choice '{turn_choice}' by player {self.player_id}.")
            completed = True
        finally:
            end_turn = getattr(self.__interface, "end_turn", None)
            if callable(end_turn):
                end_turn(completed)

    # prompts for each option
    def __prompt_draw_train(self):
        """Handle the draw-train-cards portion of a turn."""
        self.__draw_train_cards()

    def __prompt_claim_route(self, fault_flags: Dict[str, bool]):
        """Handle a player's attempt to claim a route."""
        # does it already have a fault flag?
        if not fault_flags['claim_route']:
            # should it have a fault flag?
            if not len(self.get_affordable_routes()):
                # if so, add one, throw an error message, and try again
                fault_flags["claim_route"] = True
                print(f"{self.name} cannot currently afford any routes. Try something else.")
                self.take_turn(fault_flags)
            else:
                # if not, proceed as normal
                route = self.__claim_available_route(fault_flags["draw_train"])
                self.update_longest_path(route)
                self.check_ticket_completion()
        elif not fault_flags['draw_train']:
            self.__draw_train_cards([-1]*2)

    def __prompt_draw_ticket(self, fault_flags: Dict[str, bool]):
        """Handle drawing destination tickets during a turn."""
        # does it already have a fault flag?
        if not fault_flags['draw_destination']:
            # should it have a fault flag?
            if len(self.context.ticket_deck) < 3:
                # if so, add one, throw an error message, and try again
                fault_flags["draw_destination"] = True
                print(f"There aren't enough destination tickets left for {self.name}. Try something else.")
                self.take_turn(fault_flags)
            else:
                # if not, proceed as normal
                success = self.__draw_destination_tickets()
                if not success:
                    fault_flags["draw_destination"] = True
                    print(f"{self.player_id} could not draw destination tickets.")
                    self.take_turn(fault_flags)
        else:
            self.__draw_train_cards([-1]*2)

    # handlers for each option
    def __draw_train_cards(self, draws: Optional[List[int]] = None) -> str:
        """Internal helper for drawing train cards."""
        draw_choices = [self.__interface.choose_draw_train_action() for _ in range(2)] if draws is None else draws

        train_deck = self.context.train_deck # Assuming ticket_deck includes train draw functionality

        # If a card chosen from the face_up_cards is a locomotive
        for c in draw_choices:
            if self.context.face_up_cards[c] == 'L' and c >= 0:
                try:
                    card = train_deck.draw_face_up(c)
                    self.__add_cards([card], True)
                    return 'success'
                except IndexError:
                    print(f"Invalid face-up index '{c}' by player {self.player_id}.")
                    return 'invalid'
                
        first_choice = draw_choices[0]
        if first_choice >= 0:
            try:
                card = train_deck.draw_face_up(first_choice)
                self.__add_cards([card], True)
            except IndexError:
                print(f"Invalid face-up index '{first_choice}' by player {self.player_id}.")
                return 'invalid'

        elif first_choice == -1:
            try:
                card = train_deck.draw_face_down()
                self.__add_cards([card], False)
            except Exception as e:
                print(f"Face-down draw failed for player {self.player_id}: {e}")
                return 'invalid'

        else:
            print(f"Invalid draw choice '{first_choice}' by player {self.player_id}.")
            return 'invalid'

        second_choice = draw_choices[1]
        if second_choice >= 0:
            try:
                card = train_deck.draw_face_up(second_choice)
                self.__add_cards([card], True)
            except IndexError:
                print(f"Invalid face-up index '{second_choice}' by player {self.player_id}.")
                return 'invalid'

        elif second_choice == -1:
            try:
                card = train_deck.draw_face_down()
                self.__add_cards([card], False)
            except Exception as e:
                print(f"Face-down draw failed for player {self.player_id}: {e}")
                return 'invalid'

        else:
            print(f"Invalid draw choice '{second_choice}' by player {self.player_id}.")
            return 'invalid'

        return 'success'
    
    def __claim_available_route(self, l_fault: Optional[bool]) -> Route:
        """Spend cards and claim a route chosen by the interface."""
        affordable_routes = self.get_affordable_routes()
        route, l_count = self.__interface.choose_route_to_claim(affordable_routes)
        if l_count > self.__train_hand.get("L", 0):
            print(f"Player {self.name} doesn't have {l_count} locomotives to spend; try again.")
            if not l_fault:
                self.__claim_available_route(True)
            else:
                l_count = 0
        affordable_routes = [r for (r, l) in affordable_routes if l <= l_count]
        if route not in affordable_routes:
            print(f"Player {self.name} can't afford route {route} this turn; we've chosen {affordable_routes[0]} for you instead")
            route = affordable_routes[0]
        cards_to_spend = []
        if l_count >= route.length:
            l_count = route.length
        else:
            if route.color == "X":
                color_options = [c for c in self.__train_hand.keys() if self.__train_hand.get(c, 0) >= (route.length - l_count) and c != 'L']
                if len(color_options) >= 1:
                    chosen_color = self.__interface.choose_color_to_spend(route, color_options)
                    # set color_to_spend to chosen_color if chosen_color is a valid color that they have enough of; otherwise set it to the one they have the most of
                    color_to_spend = chosen_color if self.__train_hand.get(chosen_color, 0) >= (route.length - l_count) else self.get_no_locomotives().most_common(1)[0][0]
                else:
                    color_to_spend = color_options[0]
            else:
                color_to_spend = route.color
            cards_to_spend.extend([color_to_spend] * (route.length - l_count))
        cards_to_spend.extend(["L"] * l_count)
        if self._spend_cards.__self__ != self:
            pass
        self._spend_cards(cards_to_spend)
        self.__claim_route(route)
        return route

    def __draw_destination_tickets(self) -> bool:
        """Offer destination tickets and keep the chosen ones."""
        try:
            offer = self.context.ticket_deck.deal_unique(3)
        except Exception as e:
            print(f"Ticket draw failed for player {self.player_id}: {e}")
            return False

        if not offer:
            print(f"No destination tickets available for {self.player_id}.")
            return False

        kept = self.__interface.select_ticket_offer(offer)
        if not kept:
            print(f"{self.player_id} kept no tickets from offer.")
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
        correction_list = []
        for k in self.exposed.keys():
            if self.exposed.get(k, 0) < 0:
                correction_list.append(k)
        for k in correction_list:
            self.exposed[k] = 0

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
        affordable_routes = []
        available_routes = self.context.map.get_available_routes(self.player_id)
        
        for r in available_routes:
            for n in range(0, self.__train_hand.get("L", 0) + 1):
                # if the player has enough of the color in hand or if the color is gray and the player has enough of their most common color in hand
                most_common_num = 0 if self.get_no_locomotives().total() == 0 else self.get_no_locomotives().most_common(1)[0][1] # type: ignore
                if self.get_no_locomotives().get(r.color, 0) >= (r.length - n) or (r.color == "X" and most_common_num >= (r.length - n)):
                    if r not in [r for (r, _) in affordable_routes]:
                        affordable_routes.append((r, n))
        return affordable_routes
    
    def update_longest_path(self, new_route: Route):
        """Notify the map that this player claimed a new route."""
        self.context.map.update_longest_path(self.player_id, new_route)
        my_longest_path = self.context.map.longest_paths[self.player_id]
        has_longest_path = (self.context.map.longest_path_holder == self.player_id)

    def check_ticket_completion(self):
        """Update ticket completion status based on owned routes."""
        # TODO: also detect tickets that can no longer be completed and score
        # them immediately (as failed) instead of waiting for game end:
        #  - the two cities are cut off from each other in this player's
        #    culled map (every remaining connecting path needs a route already
        #    claimed by another player), or
        #  - the cheapest completing path in the culled map costs more trains
        #    than the player has remaining.
        # Depends on the per-player culled/contracted map planned for
        # MapGraph (merged claimed components + only-claimable-by-me routes).
        path_info = self.context.map.paths[self.player_id]
        for t in [t for t in self.__tickets if not t.is_completed]:
            city_1_group = next((group for group in path_info if t.city1 in group), None)
            if city_1_group != None and t.city2 in city_1_group:
                t.is_completed = True

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(id={self.player_id}, trains={self.trains_remaining}, "
                f"hand={dict(self.__train_hand)}, tickets={self.__tickets})")


