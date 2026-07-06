"""Action types and legal-move enumeration.

A turn is one action from legal_turn_actions plus its follow-ups (a second
card pick, or a ticket-keep choice). Bots implement
`act(view, legal_actions) -> action`; anything outside the menu is replaced
with the menu's first entry, so illegal play is impossible by construction.
"""
from dataclasses import dataclass
from itertools import combinations
from typing import List, Tuple


@dataclass(frozen=True)
class Action:
    pass


@dataclass(frozen=True)
class Pass(Action):
    """Nothing legal to do this turn."""


@dataclass(frozen=True)
class DrawBlind(Action):
    """Draw the top card of the face-down deck."""


@dataclass(frozen=True)
class DrawFaceUp(Action):
    """Take the market card at `index` (currently `card`)."""
    index: int
    card: str


@dataclass(frozen=True)
class ClaimRoute(Action):
    """Claim `route_id`, spending `locomotives` L cards plus `color` cards
    for the rest (`color` is "L" when locomotives cover the whole route)."""
    route_id: str
    color: str
    locomotives: int


@dataclass(frozen=True)
class DrawTickets(Action):
    """Take a destination-ticket offer (followed by a keep_tickets decision)."""


@dataclass(frozen=True)
class KeepTickets(Action):
    """Keep the offer tickets at these indices; return the rest."""
    indices: Tuple[int, ...]


def legal_turn_actions(player) -> List[Action]:
    """Everything the player may open their turn with.

    Rules as written: a blind draw needs at least one card across the draw
    and discard piles (the deck reshuffles the moment it empties), face-up
    cards are takeable whenever the market has any, tickets need a 3-card
    offer.
    """
    game = player.game_context
    actions: List[Action] = []

    deck = game.get_train_deck()
    if len(deck) or deck.get_discard_pile():
        actions.append(DrawBlind())
    actions.extend(DrawFaceUp(i, card) for i, card in enumerate(deck.get_face_up()))

    actions.extend(legal_claim_actions(player))

    if len(game.get_ticket_deck()) >= 3:
        actions.append(DrawTickets())

    return actions or [Pass()]


def legal_second_draw_actions(player) -> List[Action]:
    """The second card pick: face-up locomotives are off the menu."""
    deck = player.game_context.get_train_deck()
    actions: List[Action] = []
    if len(deck) or deck.get_discard_pile():
        actions.append(DrawBlind())
    actions.extend(
        DrawFaceUp(i, card)
        for i, card in enumerate(deck.get_face_up())
        if card != "L"
    )
    return actions or [Pass()]


def legal_claim_actions(player) -> List[ClaimRoute]:
    """Every (route, color, locomotive-count) combination the hand affords."""
    game = player.game_context
    hand = player.get_hand()
    locomotives = hand.get("L", 0)
    actions: List[ClaimRoute] = []
    for route in game.get_map().get_available_routes(player.player_id):
        if route.length > player.trains_remaining:
            continue
        for spent_locos in range(min(locomotives, route.length) + 1):
            needed = route.length - spent_locos
            if needed == 0:
                actions.append(ClaimRoute(route.route_id, "L", spent_locos))
                continue
            colors = [route.color] if route.color != "X" else [c for c in hand if c != "L"]
            for color in colors:
                if hand.get(color, 0) >= needed:
                    actions.append(ClaimRoute(route.route_id, color, spent_locos))
    return actions


def legal_keep_actions(offer_size: int, min_keep: int) -> List[KeepTickets]:
    """Every allowed subset of an offer (setup uses min_keep=2, later 1)."""
    floor = max(1, min(min_keep, offer_size))
    return [
        KeepTickets(tuple(combo))
        for size in range(floor, offer_size + 1)
        for combo in combinations(range(offer_size), size)
    ]
