"""Action types and legal-move enumeration.

A turn is one action from legal_turn_actions plus its follow-ups (a second
card pick, or a ticket-keep choice). Bots implement
`act(view, legal_actions) -> action`; anything outside the menu is replaced
with the menu's first entry, so illegal play is impossible by construction.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, product
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from ticket_to_ride.engine.state.map import Route, _route_claimable_by


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
    payment: 'Optional[Tuple[Tuple[str, int], ...]]' = None


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


def claimable_routes(
    routes: List[Route],
    siblings_by_key: 'Dict[tuple, List[Route]]',
    claim_of: 'Callable[[Route], Optional[str]]',
    player_id: str,
    player_count: int,
    trains_remaining: int,
) -> Iterator[Route]:
    """Routes the player may claim under the board rules and train supply.

    The single claimability walk shared by legal-move enumeration and both
    affordability queries (Player.get_affordable_routes,
    PlayerView.affordable_routes), parameterized over the claim source like
    _route_claimable_by so live and snapshotted state go through identical
    rules. Preserves the order of `routes`.
    """
    for route in routes:
        siblings = [
            sibling for sibling in siblings_by_key.get(route.sibling_group_key(), [])
            if sibling is not route
        ]
        if not _route_claimable_by(route, siblings, claim_of, player_id, player_count):
            continue
        if route.length > trains_remaining:
            continue
        yield route


def enumerate_claim_actions(
    routes: List[Route],
    siblings_by_key: 'Dict[tuple, List[Route]]',
    claim_of: 'Callable[[Route], Optional[str]]',
    player_id: str,
    player_count: int,
    hand: 'Counter[str]',
    trains_remaining: int,
) -> List[ClaimRoute]:
    """Every (route, color, locomotive-count) combination the hand affords."""
    locomotives = hand.get("L", 0)
    actions: List[ClaimRoute] = []
    for route in claimable_routes(routes, siblings_by_key, claim_of,
                                  player_id, player_count, trains_remaining):
        if not _is_classic_cost(route.cost):
            actions.extend(_payment_claim_actions(route, hand))
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


def _is_classic_cost(cost) -> bool:
    return (len(cost) == 1 and len(cost[0].options) == 1
            and not cost[0].is_locomotive())


def _payment_claim_actions(route: Route, hand: 'Counter[str]') -> List[ClaimRoute]:
    """Enumerate one deterministic action per distinct card multiset."""
    from ticket_to_ride.engine.state.costs import CARD_COLORS

    available_locos = hand.get("L", 0)
    loco_floor = 0
    color_components = []
    for component in route.cost:
        if component.is_locomotive():
            loco_floor += component.count
        else:
            color_components.append(component)
    if loco_floor > available_locos:
        return []

    def choices(component):
        return list(CARD_COLORS) if component.is_grey() else list(component.options)

    actions: List[ClaimRoute] = []
    seen = set()
    for assignment in product(*(choices(c) for c in color_components)):
        for substitutions in product(*(range(c.count + 1) for c in color_components)):
            total_locos = loco_floor + sum(substitutions)
            if total_locos > available_locos:
                continue
            needed: 'Counter[str]' = Counter()
            for component, color, locos in zip(color_components, assignment, substitutions):
                needed[color] += component.count - locos
            if any(hand.get(color, 0) < count for color, count in needed.items()):
                continue
            spend_key = (tuple(sorted((c, n) for c, n in needed.items() if n)),
                         total_locos)
            if spend_key in seen:
                continue
            seen.add(spend_key)
            payment = []
            color_iter = iter(zip(assignment, substitutions))
            for component in route.cost:
                payment.append(("L", component.count) if component.is_locomotive()
                               else next(color_iter))
            first_color = next(
                (color for (color, locos), component in zip(payment, route.cost)
                 if not component.is_locomotive() and component.count - locos > 0),
                "L",
            )
            actions.append(ClaimRoute(route.route_id, first_color, total_locos,
                                      tuple(payment)))
    return actions


def claim_spend(action: ClaimRoute, route: Route) -> 'Counter[str]':
    spend: 'Counter[str]' = Counter()
    if action.payment is None:
        spend["L"] = action.locomotives
        if action.color != "L":
            spend[action.color] += route.length - action.locomotives
        return spend
    spend["L"] = 0
    for (color, locos), component in zip(action.payment, route.cost):
        spend["L"] += locos
        remainder = component.count - locos
        if remainder:
            spend[color] += remainder
    return spend


def affordable_route_options(
    routes: List[Route],
    siblings_by_key: 'Dict[tuple, List[Route]]',
    claim_of: 'Callable[[Route], Optional[str]]',
    player_id: str,
    player_count: int,
    hand: 'Counter[str]',
    trains_remaining: int,
) -> 'List[Tuple[Route, int]]':
    """(route, locomotives) pairs the hand affords, using the fewest
    locomotives per route."""
    if not hand.total():
        return []
    locomotives = hand.get("L", 0)
    colors = Counter({c: n for c, n in hand.items() if c != "L" and n > 0})
    most_common = max(colors.values(), default=0)
    options: 'List[Tuple[Route, int]]' = []
    for route in claimable_routes(routes, siblings_by_key, claim_of,
                                  player_id, player_count, trains_remaining):
        if not _is_classic_cost(route.cost):
            payments = _payment_claim_actions(route, hand)
            if payments:
                options.append((route, min(a.locomotives for a in payments)))
            continue
        for n in range(locomotives + 1):
            needed = route.length - n
            if colors.get(route.color, 0) >= needed or (route.color == "X" and most_common >= needed):
                options.append((route, n))
                break
    return options


def legal_claim_actions(player) -> List[ClaimRoute]:
    """Every (route, color, locomotive-count) combination the hand affords."""
    map_graph = player.game_context.get_map()
    return enumerate_claim_actions(
        map_graph.routes,
        map_graph.sibling_index,
        lambda route: route.claimed_by,
        player.player_id,
        map_graph.player_count,
        player.get_hand(),
        player.trains_remaining,
    )


def legal_keep_actions(offer_size: int, min_keep: int) -> List[KeepTickets]:
    """Every allowed subset of an offer (setup uses min_keep=2, later 1)."""
    floor = max(1, min(min_keep, offer_size))
    return [
        KeepTickets(tuple(combo))
        for size in range(floor, offer_size + 1)
        for combo in combinations(range(offer_size), size)
    ]
