from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket


class CountOnlyDeck:
    def __init__(self, count: int) -> None:
        self.count = count

    def __len__(self) -> int:
        return self.count


@dataclass
class OpponentInfoView:
    player_id: str
    exposed_hand: Counter[str]
    num_cards_in_hand: int
    remaining_trains: int
    score: int
    destination_ticket_count: int


class MapView:
    def __init__(self, routes: List[Route]) -> None:
        self.routes = routes
        self.longest_path_holder: str = ""
        self.longest_paths: Dict[str, int] = {}
        self.paths: Dict[str, List[tuple[set[str], int]]] = {}

    def get_available_routes(self) -> List[Route]:
        return [route for route in self.routes if route.claimed_by is None]

    def get_claimed_routes(self, player_id: str) -> List[Route]:
        return [route for route in self.routes if route.claimed_by == player_id]


class PlayerContextView:
    def __init__(
        self,
        player_id: str,
        map_view: MapView,
        face_up_cards: List[str],
        turn_number: int,
        score: int,
        opponents: List[OpponentInfoView],
        train_deck_count: int,
        ticket_deck_count: int,
    ) -> None:
        self.player_id = player_id
        self.map = map_view
        self.face_up_cards = face_up_cards
        self.turn_number = turn_number
        self.score = score
        self.opponents = opponents
        self.train_deck = CountOnlyDeck(train_deck_count)
        self.ticket_deck = CountOnlyDeck(ticket_deck_count)


class PlayerView:
    def __init__(
        self,
        player_id: str,
        name: str,
        color: str,
        trains_remaining: int,
        hand: Counter[str],
        exposed: Counter[str],
        tickets: List[DestinationTicket],
        context: PlayerContextView,
    ) -> None:
        self.player_id = player_id
        self.name = name
        self.color = color
        self.trains_remaining = trains_remaining
        self.exposed = exposed
        self._hand = hand
        self._tickets = tickets
        self.context = context

    def get_affordable_routes(self) -> List[tuple[Route, int]]:
        if not self._hand.total():  # type: ignore[attr-defined]
            return []

        affordable_routes: List[tuple[Route, int]] = []
        available_routes = self.context.map.get_available_routes()

        for route in available_routes:
            for locomotives in range(0, self._hand.get("L", 0) + 1):
                most_common_num = 0 if self.get_no_locomotives().total() == 0 else self.get_no_locomotives().most_common(1)[0][1]  # type: ignore[attr-defined]
                enough_color = self.get_no_locomotives().get(route.color, 0) >= (route.length - locomotives)
                enough_gray = route.color == "X" and most_common_num >= (route.length - locomotives)
                if enough_color or enough_gray:
                    if route not in [known_route for (known_route, _) in affordable_routes]:
                        affordable_routes.append((route, locomotives))
        return affordable_routes

    def get_tickets(self) -> List[DestinationTicket]:
        return self._tickets

    def get_hand(self) -> Counter[str]:
        return self._hand

    def get_exposed(self) -> Counter[str]:
        return self.exposed

    def get_card_count(self) -> int:
        return self._hand.total()  # type: ignore[attr-defined]

    def get_no_locomotives(self) -> Counter[str]:
        without_locomotives = self._hand.copy()
        if "L" in without_locomotives:
            without_locomotives.pop("L")
        return without_locomotives


def player_view_from_payload(payload: Dict[str, Any]) -> PlayerView:
    map_view = MapView([route_from_payload(route_payload) for route_payload in payload["context"]["map"]["routes"]])
    opponents = [
        OpponentInfoView(
            player_id=opponent["playerId"],
            exposed_hand=Counter(opponent["exposedHand"]),
            num_cards_in_hand=opponent["numCardsInHand"],
            remaining_trains=opponent["remainingTrains"],
            score=opponent["score"],
            destination_ticket_count=opponent["destinationTicketCount"],
        )
        for opponent in payload["context"]["opponents"]
    ]
    context = PlayerContextView(
        player_id=payload["playerId"],
        map_view=map_view,
        face_up_cards=payload["context"]["faceUpCards"],
        turn_number=payload["context"]["turnNumber"],
        score=payload["context"]["score"],
        opponents=opponents,
        train_deck_count=payload["context"]["trainDeckCount"],
        ticket_deck_count=payload["context"]["ticketDeckCount"],
    )
    return PlayerView(
        player_id=payload["playerId"],
        name=payload["name"],
        color=payload["color"],
        trains_remaining=payload["trainsRemaining"],
        hand=Counter(payload["hand"]),
        exposed=Counter(payload["exposedHand"]),
        tickets=[ticket_from_payload(ticket_payload) for ticket_payload in payload["tickets"]],
        context=context,
    )


def route_from_payload(payload: Dict[str, Any]) -> Route:
    route = Route(payload["city1"], payload["city2"], payload["length"], payload["color"])
    route.claimed_by = payload.get("claimedBy")
    return route


def ticket_from_payload(payload: Dict[str, Any]) -> DestinationTicket:
    ticket = DestinationTicket(payload["city1"], payload["city2"], payload["value"])
    ticket.is_completed = payload.get("isCompleted", False)
    return ticket


def route_payload(route: Route) -> Dict[str, Any]:
    return {
        "city1": route.city1,
        "city2": route.city2,
        "length": route.length,
        "color": route.color,
        "claimedBy": route.claimed_by,
        "routeKey": repr(route),
    }


def ticket_payload(ticket: DestinationTicket) -> Dict[str, Any]:
    return {
        "city1": ticket.city1,
        "city2": ticket.city2,
        "value": ticket.value,
        "isCompleted": ticket.is_completed,
        "ticketKey": ticket_key(ticket),
    }


def ticket_key(ticket: DestinationTicket) -> str:
    return f"{ticket.city1}|{ticket.city2}|{ticket.value}|{int(ticket.is_completed)}"
