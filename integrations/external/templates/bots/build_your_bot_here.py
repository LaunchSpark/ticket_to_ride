from typing import List

from external.contracts.base_bot import BaseBot
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket


BOT_META = {
    "schema_version": 1,
    "id": "your_bot_id",
    "name": "Your Bot Name",
    "version": "1.0.0",
    "description": "Describe the strategy or purpose of this bot.",
    "author": "",
    "tags": [],
}


class YourBotName(BaseBot):
    META = BOT_META

    # used to determine whether to
    # 1 = Draw
    # 2 = Claim
    # 3 = draw a destination ticket
    def choose_turn_action(self) -> int:
        """Decide what action to take each turn."""
        raise NotImplementedError

    # choose what cards to draw
    def choose_draw_train_action(self) -> int:
        """Select which train cards to draw."""
        raise NotImplementedError

    # claimable_routes is a list of tuples(Route, locomotives_required)
    # return a tuple(route, locomotives_to_spend)
    def choose_route_to_claim(self, claimable_routes: "List[tuple[Route, int]]") -> "tuple[Route, int]":
        """Return the route and locomotives you wish to spend."""
        raise NotImplementedError

    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        """Pick a color to use when claiming gray routes."""
        raise NotImplementedError

    def select_ticket_offer(self, offer) -> List[DestinationTicket]:
        """Choose which destination tickets to keep from an offer."""
        raise NotImplementedError
