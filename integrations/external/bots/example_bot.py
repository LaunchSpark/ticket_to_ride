import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup:
    import heapq
    from collections import Counter
    from itertools import combinations
    from collections.abc import Collection
    from typing import List

    from external.contracts.base_bot import ActionBot
    from ticket_to_ride.engine.actions import (
        ClaimRoute,
        DrawBlind,
        DrawFaceUp,
        DrawTickets,
        KeepTickets,
    )
    from ticket_to_ride.engine.state.map import Route
    from ticket_to_ride.engine.state.decks import DestinationTicket

    BOT_META = {
        "schema_version": 1,
        "id": "example_bot",
        "name": "Example Bot",
        "version": "1.0.0",
        "description": "Reference implementation for custom Ticket to Ride bots.",
        "author": "Lucas Starkey",
        "tags": ["example"],
    }


@app.class_definition(hide_code=True)
class ExampleBot(ActionBot):
    """The most basic intelligent strategy - not optimal, just sensible.

    Plan: pick the destination-ticket pair with the best cost-to-points
    ratio (cost = sum of route point values along an exact Steiner tree,
    point value as a proxy for difficulty), grab a third ticket if it adds
    < 4 extra cost. Each turn: draw tickets when everything is scored,
    otherwise claim a planned route if one is affordable, otherwise draw
    the train cards the plan still needs. All pathfinding runs on the
    player's culled map, so the own network is free to travel through and
    opponent-claimed routes don't exist.
    """

    META = BOT_META

    # Route points by length: the "difficulty" weight used for planning.
    _ROUTE_POINTS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 10, 6: 15, 7: 18, 8: 21}
    _CARD_COLORS = ["R", "B", "U", "G", "O", "P", "W", "Y"]
    # A third offered ticket rides along if it costs less than this much
    # extra once the pair's planned routes are free.
    _EXTRA_TICKET_MAX_COST = 4

    def __init__(self) -> None:
        super().__init__()
        self._planned_routes: 'List[Route]' = []
        self._planned_route_ids: 'set[str]' = set()
        # choose_draw_train_action is called twice back-to-back before any
        # card moves, so both picks are planned on the first call and the
        # second is remembered here.

    # ------------------------------------------------------------------
    # Pathfinding over the culled map (point-value weights)
    # ------------------------------------------------------------------

    def act(self, view, legal_actions):
        self._view = view
        if view.decision == "keep_tickets":
            return self._keep_action(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw_action(view, legal_actions)
        return self._turn_action(view, legal_actions)

    def _culled(self):
        return self._view.culled_map()

    def _route_points(self, route: Route) -> int:
        return self._ROUTE_POINTS.get(route.length, route.length)

    def _adjacency(self, culled, free_route_ids: 'Collection[str]' = frozenset()):
        """node -> [(neighbor, cost, route)] with planned/free routes at cost 0."""
        adjacency = {}
        for route in culled.routes:
            node_a, node_b = culled.endpoints(route)
            cost = 0 if route.route_id in free_route_ids else self._route_points(route)
            adjacency.setdefault(node_a, []).append((node_b, cost, route))
            adjacency.setdefault(node_b, []).append((node_a, cost, route))
        return adjacency

    @staticmethod
    def _dijkstra(adjacency, source):
        distances = {source: 0}
        predecessors = {}
        frontier = [(0, source)]
        while frontier:
            distance, node = heapq.heappop(frontier)
            if distance > distances.get(node, distance):
                continue
            for neighbor, cost, route in adjacency.get(node, []):
                candidate = distance + cost
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    predecessors[neighbor] = (node, route)
                    heapq.heappush(frontier, (candidate, neighbor))
        return distances, predecessors

    @staticmethod
    def _walk_back(predecessors, source, target):
        routes = []
        node = target
        while node != source:
            node, route = predecessors[node]
            routes.append(route)
        return routes

    def _steiner_tree(self, culled, cities, free_route_ids: 'Collection[str]' = frozenset()):
        """Exact minimum Steiner tree over up to 4 cities: (cost, routes) or None.

        Terminals are the cities' culled nodes (a whole owned network counts
        as one terminal, and tickets already spanning it dedupe away). Exact
        for <=4 terminals because such a tree has at most two junction
        nodes, so scanning all junction placements covers every topology.
        """
        terminals = sorted({culled.city_to_node[city] for city in cities})
        if len(terminals) <= 1:
            return 0, []

        adjacency = self._adjacency(culled, free_route_ids)
        searches = {t: self._dijkstra(adjacency, t) for t in terminals}
        if any(t not in searches[terminals[0]][0] for t in terminals[1:]):
            return None  # some terminal is cut off

        def tree_from_paths(path_lists):
            routes_by_id = {}
            for path in path_lists:
                for route in path:
                    routes_by_id[route.route_id] = route
            routes = list(routes_by_id.values())
            cost = sum(
                0 if route.route_id in free_route_ids else self._route_points(route)
                for route in routes
            )
            return cost, routes

        if len(terminals) == 2:
            first, second = terminals
            return tree_from_paths([self._walk_back(searches[first][1], first, second)])

        nodes = list(adjacency.keys())

        if len(terminals) == 3:
            best = None
            for junction in nodes:
                if not all(junction in searches[t][0] for t in terminals):
                    continue
                candidate = tree_from_paths(
                    [self._walk_back(searches[t][1], t, junction) for t in terminals]
                )
                if best is None or candidate[0] < best[0]:
                    best = candidate
            return best

        # 4 terminals: two junctions u, v; try all three ways to pair the
        # terminals across them.
        all_searches = {node: self._dijkstra(adjacency, node) for node in nodes}
        t1, t2, t3, t4 = terminals
        pairings = [((t1, t2), (t3, t4)), ((t1, t3), (t2, t4)), ((t1, t4), (t2, t3))]
        best = None
        for (a, b), (c, d) in pairings:
            for u in nodes:
                if u not in searches[a][0] or u not in searches[b][0]:
                    continue
                for v in nodes:
                    if v not in all_searches[u][0] or v not in searches[c][0] or v not in searches[d][0]:
                        continue
                    bound = (
                        searches[a][0][u]
                        + searches[b][0][u]
                        + all_searches[u][0][v]
                        + searches[c][0][v]
                        + searches[d][0][v]
                    )
                    if best is not None and bound >= best[0]:
                        continue
                    candidate = tree_from_paths(
                        [
                            self._walk_back(searches[a][1], a, u),
                            self._walk_back(searches[b][1], b, u),
                            self._walk_back(all_searches[u][1], u, v),
                            self._walk_back(searches[c][1], c, v),
                            self._walk_back(searches[d][1], d, v),
                        ]
                    )
                    if best is None or candidate[0] < best[0]:
                        best = candidate
        return best

    def path_finder(self, city1, city2):
        """Cheapest still-claimable path between two cities, or None if cut off."""
        result = self._steiner_tree(self._culled(), [city1, city2])
        return None if result is None else result[1]

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _unscored_tickets(self):
        return [t for t in self._view.tickets if not t.is_completed and not t.is_impossible]

    def _replan(self):
        """Recompute the planned route set for every unscored ticket.

        Runs fresh on the current culled map each time, which is what
        "update the planned route to account for being cut off" means in
        practice: routes another player took simply no longer exist here.
        The first two tickets get an exact joint Steiner tree; any further
        tickets attach greedily with already-planned routes free.
        """
        culled = self._culled()
        unscored = self._unscored_tickets()

        routes: 'List[Route]' = []
        free: 'set[str]' = set()

        head, tail = unscored[:2], unscored[2:]
        if head:
            cities = [city for ticket in head for city in (ticket.city1, ticket.city2)]
            joint = self._steiner_tree(culled, cities)
            if joint is None:
                tail = unscored[1:]
                head = unscored[:1]
                joint = self._steiner_tree(culled, [head[0].city1, head[0].city2])
            if joint is not None:
                routes.extend(joint[1])
                free.update(route.route_id for route in joint[1])
        for ticket in tail:
            extra = self._steiner_tree(culled, [ticket.city1, ticket.city2], free_route_ids=free)
            if extra is not None:
                routes.extend(extra[1])
                free.update(route.route_id for route in extra[1])

        self._planned_routes = routes
        self._planned_route_ids = {route.route_id for route in routes}
        return routes

    def _card_needs(self):
        """Deficit per color under the current plan.

        Grey demand is paid in one color, so only the single largest
        surplus covers it; any grey deficit is assigned to the color with
        the biggest surplus (fewest extra draws to stack). Locomotives are
        only ever spent on the longest planned route, so they reduce that
        route's color demand and nothing else.
        """
        reserved: 'Counter[str]' = Counter()
        grey_needed = 0
        for route in self._planned_routes:
            options = route.payment_colors()
            color_spaces = route.length - route.locomotives
            if len(options) == 1:
                reserved[next(iter(options))] += color_spaces
            else:
                grey_needed += color_spaces

        hand = self._view.hand
        deficits = {c: max(0, reserved[c] - hand.get(c, 0)) for c in self._CARD_COLORS}
        surplus = {c: max(0, hand.get(c, 0) - reserved[c]) for c in self._CARD_COLORS}

        stack_color = max(self._CARD_COLORS, key=lambda c: surplus[c])
        grey_deficit = max(0, grey_needed - surplus[stack_color])
        if grey_deficit:
            deficits[stack_color] += grey_deficit

        required_locomotives = sum(route.locomotives for route in self._planned_routes)
        locomotives = max(0, hand.get("L", 0) - required_locomotives)
        if locomotives and self._planned_routes:
            longest = max(self._planned_routes, key=lambda route: route.length)
            longest_options = longest.payment_colors()
            target = (next(iter(longest_options)) if len(longest_options) == 1
                      else stack_color)
            deficits[target] = max(0, deficits[target] - locomotives)
        return deficits

    def _claimable_planned(self, affordable):
        """Affordable planned routes, honoring the locomotive rule.

        Locomotives only get spent on a route as long as the longest route
        in the plan; anything cheaper that would burn them waits (we draw
        instead).
        """
        max_planned_length = max((route.length for route in self._planned_routes), default=0)
        picks = []
        for route, locomotives in affordable:
            if route.route_id not in self._planned_route_ids:
                continue
            if (locomotives > route.locomotives
                    and route.length != max_planned_length):
                continue
            picks.append((route, locomotives))
        return picks

    # ------------------------------------------------------------------
    # Engine-facing decisions
    # ------------------------------------------------------------------

    def _turn_action(self, view, legal_actions):
        """Tickets all scored -> draw more; else claim if a planned route is
        affordable; else draw train cards."""
        claims = [a for a in legal_actions if isinstance(a, ClaimRoute)]
        draws = [a for a in legal_actions if isinstance(a, (DrawBlind, DrawFaceUp))]
        tickets_offered = any(isinstance(a, DrawTickets) for a in legal_actions)

        if not self._unscored_tickets():
            if tickets_offered:
                return DrawTickets()
            # Deck can't serve an offer: score points instead of stalling.
            if claims:
                return self._claim_action(view, claims)
            if draws:
                return self._draw_action(view, draws)
            return legal_actions[0]

        self._replan()
        if claims and self._claimable_planned(self._picks_from_claims(view, claims)):
            return self._claim_action(view, claims)
        if draws:
            return self._draw_action(view, draws)
        if claims:  # forced: train deck is dry
            return self._claim_action(view, claims)
        if tickets_offered:
            return DrawTickets()
        return legal_actions[0]

    @staticmethod
    def _picks_from_claims(view, claims):
        """Rebuild (route, locomotives) picks — one per route at its minimum
        locomotive spend — so the pre-action planning helpers keep working."""
        best = {}
        for action in claims:
            current = best.get(action.route_id)
            if current is None or action.locomotives < current[1]:
                best[action.route_id] = (view.route_by_id(action.route_id), action.locomotives)
        return list(best.values())

    def _claim_action(self, view, claims):
        picks = self._picks_from_claims(view, claims)
        route, locomotives = self._choose_route_pick(picks)
        candidates = [a for a in claims if a.route_id == route.route_id and a.locomotives == locomotives]
        if not candidates:
            candidates = [a for a in claims if a.route_id == route.route_id] or claims
        if len(candidates) == 1:
            return candidates[0]
        # Gray route: spend the color the plan needs least (largest surplus
        # stack first, so reserved colors stay untouched).
        needs = self._card_needs()
        hand = view.hand
        return min(candidates, key=lambda a: (needs.get(a.color, 0), -hand.get(a.color, 0)))

    def _choose_route_pick(self, claimable_routes: 'List[tuple[Route, int]]') -> 'tuple[Route, int]':
        """Most expensive affordable planned route; forced claims dump the
        least-needed cards on the shortest gray route available."""
        self._replan()
        planned = self._claimable_planned(claimable_routes)
        if planned:
            return max(planned, key=lambda pick: self._route_points(pick[0]))

        # Forced claim (train deck dry, or nothing planned is affordable):
        # spend what the plan values least. Gray routes let us choose the
        # dump color; otherwise prefer colors we need least, shortest first.
        needs = self._card_needs()
        options = [pick for pick in claimable_routes if pick[1] == 0] or list(claimable_routes)
        gray = [pick for pick in options if len(pick[0].payment_colors()) != 1]
        if gray:
            return min(gray, key=lambda pick: pick[0].length)
        return min(options, key=lambda pick: (needs.get(pick[0].color, 0), pick[0].length))

    def _draw_action(self, view, draw_actions):
        """Best single pick against the market as it is right now: biggest
        deficit color first, never a face-up locomotive, else the deck.

        (The old two-pick planning and its _queued_draw hack are obsolete:
        the engine now shows the refreshed market before the second pick.)
        """
        self._replan()
        needs = self._card_needs()
        useful = [
            a for a in draw_actions
            if isinstance(a, DrawFaceUp) and a.card != "L" and needs.get(a.card, 0) > 0
        ]
        if useful:
            return max(useful, key=lambda a: needs[a.card])
        for action in draw_actions:
            if isinstance(action, DrawBlind):
                return action
        return draw_actions[0]

    def _keep_action(self, view, legal_actions):
        kept = self._select_tickets(view.ticket_offer)
        indices = tuple(sorted(view.ticket_offer.index(t) for t in kept))
        choice = KeepTickets(indices)
        if choice in legal_actions:
            return choice
        supersets = [
            a for a in legal_actions
            if isinstance(a, KeepTickets) and set(indices) <= set(a.indices)
        ]
        if supersets:
            return min(supersets, key=lambda a: len(a.indices))
        return legal_actions[0]

    def _select_tickets(self, offer: List[DestinationTicket]) -> List[DestinationTicket]:
        """Initial offer: keep the pair with the best Steiner cost/points
        ratio, plus a third ticket if it adds < 4 extra cost. Later offers:
        keep everything already completed plus the single best-ratio viable
        ticket. Never keep nothing (the engine fails the draw): fall back to
        the lowest-value ticket to minimize the penalty."""
        culled = self._culled()

        keep = [t for t in offer if culled.connected(t.city1, t.city2)]  # free points
        candidates = [t for t in offer if t not in keep]
        viable = []
        for ticket in candidates:
            trains = culled.cheapest_connection(ticket.city1, ticket.city2)
            if trains is not None and trains <= self._view.trains_remaining:
                viable.append(ticket)

        if not self._view.tickets:
            keep.extend(self._pick_initial_tickets(culled, viable))
        elif viable:
            self._replan()
            free = set(self._planned_route_ids)
            best = None
            for ticket in viable:
                attachment = self._steiner_tree(culled, [ticket.city1, ticket.city2], free_route_ids=free)
                if attachment is None:
                    continue
                ratio = attachment[0] / ticket.value
                if best is None or ratio < best[0] or (ratio == best[0] and ticket.value > best[1].value):
                    best = (ratio, ticket)
            if best is not None:
                keep.append(best[1])

        if not keep:
            keep = [min(offer, key=lambda ticket: ticket.value)]
        return keep

    def _pick_initial_tickets(self, culled, viable):
        """Best cost/points pair by exact Steiner tree, plus a cheap third."""
        best = None
        for first, second in combinations(viable, 2):
            cities = [first.city1, first.city2, second.city1, second.city2]
            tree = self._steiner_tree(culled, cities)
            if tree is None:
                continue
            points = first.value + second.value
            ratio = tree[0] / points
            if best is None or ratio < best[0] or (ratio == best[0] and points > best[1]):
                best = (ratio, points, [first, second], tree[1])
        if best is None:
            return list(viable)  # 0 or 1 viable tickets: keep what there is

        chosen = list(best[2])
        free = {route.route_id for route in best[3]}
        for ticket in viable:
            if ticket in chosen:
                continue
            extra = self._steiner_tree(culled, [ticket.city1, ticket.city2], free_route_ids=free)
            if extra is not None and extra[0] < self._EXTRA_TICKET_MAX_COST:
                chosen.append(ticket)
                free.update(route.route_id for route in extra[1])
        return chosen


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers, rounds_picker = spectate_controls(
        mo,
        bot_name=BOT_META["name"],
        bot_class=ExampleBot,
        title=BOT_META["name"],
    )
    return map_picker, mo, rounds_picker, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, mo, rounds_picker, seat_pickers):
    from notebook_harness.spectate import play_match

    harness_game = play_match(mo, map_picker, seat_pickers, rounds_picker)
    return (harness_game,)


@app.cell(hide_code=True)
def _(harness_game, mo):
    from notebook_harness.spectate import spectate_widgets

    shell = spectate_widgets(mo, harness_game)
    return (shell,)


@app.cell(hide_code=True)
def _(harness_game, mo, shell):
    from notebook_harness.spectate import spectate_view

    spectate_view(mo, harness_game, shell)
    return


if __name__ == "__main__":
    app.run()
