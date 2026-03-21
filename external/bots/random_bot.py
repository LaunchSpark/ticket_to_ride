from typing import List
from external.contracts.abstract_interface import Interface
import random

from ticket_to_ride.engine.state.map import MapGraph
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket

class RandomBot(Interface):
    """Baseline bot that makes random choices.

    Helpful functions and attributes
    -------------------------------
    ``self.player`` is assigned by the game engine and exposes many helpers for
    making decisions. Some commonly used ones are listed below.

    ``self.player.get_affordable_routes()`` -> ``List[tuple[Route, int]]``
        Returns the routes you can currently afford and the locomotives required.
        Example::

            options = self.player.get_affordable_routes()
            if options:
                route, loco_needed = options[0]

    ``self.player.get_tickets()`` -> ``List[DestinationTicket]``
        Your destination tickets. Each ticket has ``city1``, ``city2``,
        ``value`` and ``is_completed`` attributes.
        Example::

            incomplete = [t for t in self.player.get_tickets() if not t.is_completed]

    ``self.player.get_hand()`` -> ``Counter[str]``
        Current train cards in hand, keyed by color letter.
        Example::

            red_cards = self.player.get_hand().get('R', 0)

    ``self.player.trains_remaining``
        How many trains you still have available.
        Example::

            if self.player.trains_remaining <= 2:
                # game will end soon
                pass

    ``self.player.context`` -> :class:`PlayerContext`
        Snapshot of public game state each turn. Useful fields include:

        - ``face_up_cards``: visible train cards in the market.
          Example::

              first = self.player.context.face_up_cards[0]

        - ``map``: :class:`MapGraph` representing the board. You can inspect
          routes via ``self.player.context.map.get_available_routes()`` or
          ``get_claimed_routes(player_id)``.

        - ``opponents``: list of ``OpponentInfo`` with each opponent's exposed
          cards, remaining trains, score and ticket count.
          Example::

              for opp in self.player.context.opponents:
                  print(opp.player_id, opp.score)

        - ``turn_number``: current turn index.
        - ``score``: your current score so far.
    """

    # used to determine weather to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self):
        """Decide which action to take this turn."""
        affordable_routes = self.player.get_affordable_routes() if self.player else None
        if not len([t for t in self.player.get_tickets() if not t.is_completed]):
            return 3
        elif affordable_routes:
            return 2
        else:
            return 1




    ##############################################################################################
    # now that you`ve decided what action to take on your turn, decide how to handle each action #
    ##############################################################################################


    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Choose which face-up index to draw or ``-1`` for the deck."""
        return random.randrange(-1, 5)

    # choose what routes to claim -------------------------------------------------------------------#
    # claimable_routes is a list of tuples( Route , number of locomotives needed to claim)           #
    # return a tuple (route, number of locomotives you wish to spend)                                #
    # so to buy a route that costs 2 of a color using 1 locomotive you could return tuple(route, 1)  #
    # error handling is done on the back end --------------------------------------------------------#
    def choose_route_to_claim(self, claimable_routes: 'List[tuple[Route,int]]') -> 'tuple[Route,int]':
        """Select a route and number of locomotives to spend."""
        return claimable_routes[random.randrange(0, len(claimable_routes))]

    # choose what color to spend on a gray route (will spend most common color on input of None or on invalid color input)
    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Pick a color to spend on gray routes."""
        return None

    # choose which destination tickets to keep
    def select_ticket_offer(self, offer) -> List[DestinationTicket]:
        """Choose which destination tickets to keep."""
        return [offer[0], offer[1]]


    #######################
    #       helpers       #
    #######################

    def path_finder(self, city1, city2):
        """Placeholder for path-finding logic."""
        return None
