from typing import List
from external.contracts.abstract_interface import Interface
import random

from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket

class YourBotName(Interface):



    # used to determine weather to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self) -> int:
        """Decide what action to take each turn."""
        pass




    ##############################################################################################
    # now that you`ve decided what action to take on your turn, decide how to handle each action #
    ##############################################################################################


    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Select which train cards to draw."""
        pass

    # choose what routes to claim -------------------------------------------------------------------#
    # claimable_routes is a list of tuples( Route , number of locomotives needed to claim)           #
    # return a tuple (route, number of locomotives you wish to spend)                                #
    # so to buy a route that costs 2 of a color using 1 locomotive you could return tuple(route, 1)  #
    # error handling is done on the back end --------------------------------------------------------#
    def choose_route_to_claim(self, claimable_routes: 'List[tuple[Route,int]]') -> 'tuple[Route,int]':
        """Return the route and locomotives you wish to spend."""
        pass

    # choose what color to spend on a gray route (will spend most common color on input of None or on invalid color input)
    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Pick a color to use when claiming gray routes."""
        pass

    # choose which destination tickets to keep must keep at least 1
    def select_ticket_offer(self, offer) -> List[DestinationTicket]:
        """Choose which destination tickets to keep from an offer."""
        pass
