from typing import List
from external.contracts.abstract_interface import Interface
import random

from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket

class ExampleBot(Interface): # TODO: actually build the thing
    # used to determine weather to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self):
        """Select which action to take on a turn."""
        return random.randrange(1, 3)


    ##############################################################################################
    # now that you`ve decided what action to take on your turn, decide how to handle each action #
    ##############################################################################################


    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Pick which train card position to draw from."""
        return random.randrange(-1, 5)

    # choose what routes to claim
    def choose_route_to_claim(self, claimable_routes: List[Route]) -> Route:
        """Select a route to claim from the provided options."""
        return claimable_routes[random.randrange(0, len(claimable_routes))]

    # choose what color to spend on a gray route (will spend most common color on input of None or on invalid color input)
    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Decide which color cards to spend on a gray route."""
        return None

    # choose which destination tickets to keep
    def select_ticket_offer(self, offer: List[DestinationTicket]) -> List[DestinationTicket]:
        """Choose which destination tickets to keep from an offer."""
        return [offer[0], offer[1]]


    #######################
    #       helpers       #
    #######################

    def path_finder(self, city1, city2):
        """Placeholder helper for possible path calculations."""
        return None
