import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup:
    import heapq
    from collections import Counter
    from dataclasses import replace
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
        claim_spend,
    )
    from ticket_to_ride.engine.state.map import Route
    from ticket_to_ride.engine.state.decks import DestinationTicket

    BOT_META = {
        "schema_version": 1,
        "id": "codex_best_bot",
        "name": "Codex Best Bot",
        "version": "1.2.0",
        "description": "Expected-turn portfolio bot with risk-adjusted route ordering.",
        "author": "OpenAI Codex",
        "tags": ["example", "qualifier", "codex"],
    }


@app.class_definition(hide_code=True)
class CodexBestBot(ActionBot):
    """Non-ML expected-turn portfolio planner.

    Ticket paths use stable route-point weights, while final decisions
    aggregate every planned cost component and evaluate the evolving hand.
    A bounded Bellman DP prices small blind-draw portfolios exactly; large
    portfolios use a joint-probability bound. Legal claims are evaluated by
    their exact post-payment state, visible and blind draws by marginal
    portfolio value, and route order by replacement cost plus opponents'
    public card readiness. This captures cascading wild-card/bycatch effects
    without putting exponential work in the pathfinding hot loop.
    """

    META = BOT_META

    # Route points by length: the "difficulty" weight used for planning.
    _ROUTE_POINTS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 10, 6: 15}
    _CARD_COLORS = ["R", "B", "U", "G", "O", "P", "W", "Y"]
    # A third offered ticket rides along if it costs less than this many
    # extra expected turns once the pair's planned routes are free.
    _EXTRA_TICKET_MAX_COST = 4
    # Only truly irreplaceable planned routes (infinite replacement cost)
    # jump ahead of higher-scoring planned claims by default.
    _CRITICAL_ROUTE_PRESSURE = 999.0
    # Once either side can approach the endgame, prefer an affordable route
    # worth at least four points over another ticket draw. Mirrored
    # Example-Bot sweeps put eight trains at the best score/tempo boundary;
    # ten was already too conservative.
    _LATE_GAME_TRAINS = 8
    _OPPONENT_ENDGAME_TRAINS = 8
    _OPPORTUNITY_MIN_POINTS = 4
    # Exact blind-draw Bellman states are cheap while the product of the
    # remaining per-color quotas stays small. Above this, use a conservative
    # joint-probability bound so large ticket portfolios stay constant-time.
    _PORTFOLIO_DP_MAX_STATES = 256

    def __init__(self) -> None:
        super().__init__()
        self._planned_routes: 'List[Route]' = []
        self._planned_route_ids: 'set[str]' = set()
        # choose_draw_train_action is called twice back-to-back before any
        # card moves, so both picks are planned on the first call and the
        # second is remembered here.

    # ------------------------------------------------------------------
    # Pathfinding over the culled map (expected-turn weights)
    # ------------------------------------------------------------------

    def act(self, view, legal_actions):
        self._prime_view(view)
        if view.decision == "keep_tickets":
            return self._keep_action(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw_action(view, legal_actions)
        return self._turn_action(view, legal_actions)

    def _culled(self):
        return self._view.culled_map()

    def _route_points(self, route: Route) -> int:
        return self._ROUTE_POINTS.get(route.length, route.length)

    def _prime_view(self, view) -> None:
        """Cache the per-decision lookups every _route_cost call shares."""
        self._view = view
        self._odds = view.draw_odds()
        self._portfolio_cache = {}
        self._blind_draw_cache = {}
        self._ticket_plan_cache = {}
        self._route_pressure_cache = {}
        self._replan_result = None

    @staticmethod
    def _hand_key(hand) -> tuple:
        return tuple(sorted((color, count) for color, count in hand.items() if count > 0))

    @staticmethod
    def _face_up_key(face_up_cards) -> tuple:
        return tuple(sorted(Counter(face_up_cards).items()))

    def _color_load(self, demand, color, hand, face_up) -> float:
        """Expected picks for one color, used only to assign flexible components."""
        deficit = max(0, demand - hand.get(color, 0))
        certain = min(deficit, face_up.get(color, 0))
        remaining = deficit - certain
        odds = self._odds.get(color, 0.0) + self._odds.get("L", 0.0)
        if remaining and odds <= 0.0:
            return float("inf")
        return certain + (remaining / odds if remaining else 0.0)

    def _portfolio_requirements(self, routes, hand, face_up_cards):
        """Aggregate route components into one color portfolio and L floor.

        Fixed components accumulate directly. Each grey/either-or component
        must stay uniform, so it is assigned whole to the color with the
        smallest marginal expected-pick load. Processing the most constrained
        and largest components first gives almost all of exhaustive assignment's
        benefit in O(components * colors), including on mixed-cost maps.
        """
        demand: 'Counter[str]' = Counter()
        flexible = []
        locomotive_floor = 0
        for route in routes:
            component_floor = 0
            for component in route.cost:
                if component.is_locomotive():
                    component_floor += component.count
                    continue
                options = component.concrete_options()
                if len(options) == 1:
                    demand[options[0]] += component.count
                else:
                    flexible.append((component.count, options))
            locomotive_floor += max(route.locomotives, component_floor)

        face_up = Counter(face_up_cards)
        flexible.sort(key=lambda item: (len(item[1]), -item[0]))
        color_rank = {color: index for index, color in enumerate(self._CARD_COLORS)}
        for count, options in flexible:
            color = min(
                options,
                key=lambda candidate: (
                    self._color_load(demand[candidate] + count, candidate, hand, face_up)
                    - self._color_load(demand[candidate], candidate, hand, face_up),
                    -hand.get(candidate, 0),
                    -self._odds.get(candidate, 0.0),
                    color_rank[candidate],
                ),
            )
            demand[color] += count
        return demand, locomotive_floor

    def _portfolio_deficits(self, routes, hand, face_up_cards):
        demand, locomotive_floor = self._portfolio_requirements(
            routes, hand, face_up_cards
        )
        deficits = Counter({
            color: max(0, demand[color] - hand.get(color, 0))
            for color in self._CARD_COLORS
        })
        locomotive_deficit = max(0, locomotive_floor - hand.get("L", 0))
        spare_locomotives = max(0, hand.get("L", 0) - locomotive_floor)
        face_up = Counter(face_up_cards)

        # Spend held wilds where each one removes the most expected future
        # work. A deficit currently covered by a face-up card saves one pick;
        # otherwise it saves roughly 1 / P(color) blind draws.
        while spare_locomotives and any(deficits.values()):
            def marginal(color):
                deficit = deficits[color]
                if not deficit:
                    return -1.0
                if deficit <= face_up.get(color, 0):
                    return 1.0
                return 1.0 / max(self._odds.get(color, 0.0), 1e-12)

            target = max(self._CARD_COLORS, key=marginal)
            deficits[target] -= 1
            spare_locomotives -= 1
        return deficits, locomotive_deficit

    def _blind_draw_fallback(self, deficits, locomotive_deficit) -> float:
        """Joint-probability lower bound for portfolios too large for exact DP."""
        locomotive_odds = self._odds.get("L", 0.0)
        active = [
            (color, deficit) for color, deficit in zip(self._CARD_COLORS, deficits)
            if deficit
        ]
        useful_odds = sum(self._odds.get(color, 0.0) for color, _ in active)
        if locomotive_deficit or active:
            useful_odds += locomotive_odds
        if useful_odds <= 0.0:
            return float("inf")

        total_bound = (sum(deficits) + locomotive_deficit) / useful_odds
        color_bound = max(
            (deficit / (self._odds.get(color, 0.0) + locomotive_odds)
             if self._odds.get(color, 0.0) + locomotive_odds > 0.0
             else float("inf"))
            for color, deficit in active
        ) if active else 0.0
        locomotive_bound = (
            locomotive_deficit / locomotive_odds
            if locomotive_deficit and locomotive_odds > 0.0
            else (float("inf") if locomotive_deficit else 0.0)
        )
        return max(total_bound, color_bound, locomotive_bound)

    def _blind_draw_dp(self, deficits, locomotive_deficit) -> float:
        """Bellman expectation for blind draws toward the whole portfolio."""
        key = (tuple(deficits), locomotive_deficit)
        cached = self._blind_draw_cache.get(key)
        if cached is not None:
            return cached
        if not locomotive_deficit and not any(deficits):
            return 0.0

        weighted_future = 0.0
        progress_odds = 0.0
        for index, color in enumerate(self._CARD_COLORS):
            if not deficits[index]:
                continue
            probability = self._odds.get(color, 0.0)
            if probability <= 0.0:
                continue
            next_deficits = list(deficits)
            next_deficits[index] -= 1
            progress_odds += probability
            weighted_future += probability * self._blind_draw_dp(
                tuple(next_deficits), locomotive_deficit
            )

        locomotive_odds = self._odds.get("L", 0.0)
        if locomotive_odds > 0.0:
            if locomotive_deficit:
                locomotive_future = self._blind_draw_dp(
                    deficits, locomotive_deficit - 1
                )
            else:
                locomotive_future = min(
                    self._blind_draw_dp(
                        tuple(
                            value - 1 if position == index else value
                            for position, value in enumerate(deficits)
                        ),
                        0,
                    )
                    for index, deficit in enumerate(deficits)
                    if deficit
                )
            progress_odds += locomotive_odds
            weighted_future += locomotive_odds * locomotive_future

        value = (
            (1.0 + weighted_future) / progress_odds
            if progress_odds > 0.0 else float("inf")
        )
        self._blind_draw_cache[key] = value
        return value

    def _expected_blind_draws(self, deficits, locomotive_deficit) -> float:
        state_count = locomotive_deficit + 1
        for deficit in deficits:
            state_count *= deficit + 1
            if state_count > self._PORTFOLIO_DP_MAX_STATES:
                return self._blind_draw_fallback(deficits, locomotive_deficit)
        return self._blind_draw_dp(tuple(deficits), locomotive_deficit)

    def _portfolio_expected_turns(self, routes, hand=None, face_up_cards=None) -> float:
        """Expected draw + claim turns for the route portfolio from this state."""
        routes = tuple({route.route_id: route for route in routes}.values())
        if not routes:
            return 0.0
        hand = Counter(self._view.hand if hand is None else hand)
        face_up_cards = tuple(
            self._view.face_up_cards if face_up_cards is None else face_up_cards
        )
        key = (
            tuple(sorted(route.route_id for route in routes)),
            self._hand_key(hand),
            self._face_up_key(face_up_cards),
        )
        if key in self._portfolio_cache:
            return self._portfolio_cache[key]

        deficits, locomotive_deficit = self._portfolio_deficits(
            routes, hand, face_up_cards
        )
        face_up = Counter(face_up_cards)
        certain_picks = 0
        for color in self._CARD_COLORS:
            certain = min(deficits[color], face_up.get(color, 0))
            deficits[color] -= certain
            certain_picks += certain

        # A visible locomotive consumes a full turn, unlike an ordinary
        # face-up card. Only assume it for a mandatory ferry/L floor.
        certain_locomotive_turns = min(
            locomotive_deficit, face_up.get("L", 0)
        )
        locomotive_deficit -= certain_locomotive_turns
        blind_draws = self._expected_blind_draws(
            tuple(deficits[color] for color in self._CARD_COLORS),
            locomotive_deficit,
        )
        value = (
            len(routes)
            + certain_locomotive_turns
            + (certain_picks + blind_draws) / 2.0
        )
        self._portfolio_cache[key] = value
        return value

    def _route_cost(self, route: Route) -> float:
        """Stable structural path weight; hand state belongs in action DP.

        Repricing topology from the current hand/market made the chosen path
        thrash after nearly every draw. Route points are deterministic, favor
        train-efficient ticket networks, and leave the portfolio evaluator to
        optimize how that fixed network is acquired and paid for.
        """
        return self._route_points(route)

    def _adjacency(self, culled, free_route_ids: 'Collection[str]' = frozenset()):
        """node -> [(neighbor, cost, route)] with planned/free routes at cost 0."""
        adjacency = {}
        for route in culled.routes:
            node_a, node_b = culled.endpoints(route)
            cost = 0 if route.route_id in free_route_ids else self._route_cost(route)
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
                self._route_cost(route)
                for route in routes if route.route_id not in free_route_ids
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

    def _plan_for_tickets(self, culled, tickets):
        cache_key = (
            tuple(sorted(route.route_id for route in culled.routes)),
            tuple((ticket.city1, ticket.city2, ticket.value) for ticket in tickets),
        )
        if cache_key in self._ticket_plan_cache:
            return self._ticket_plan_cache[cache_key]
        routes: 'List[Route]' = []
        free: 'set[str]' = set()

        head, tail = tickets[:2], tickets[2:]
        if head:
            cities = [city for ticket in head for city in (ticket.city1, ticket.city2)]
            joint = self._steiner_tree(culled, cities)
            if joint is None and len(head) > 1:
                tail = tickets[1:]
                head = tickets[:1]
                joint = self._steiner_tree(culled, [head[0].city1, head[0].city2])
            if joint is None:
                self._ticket_plan_cache[cache_key] = None
                return None
            routes.extend(joint[1])
            free.update(route.route_id for route in joint[1])

        for ticket in tail:
            extra = self._steiner_tree(culled, [ticket.city1, ticket.city2], free_route_ids=free)
            if extra is not None:
                routes.extend(extra[1])
                free.update(route.route_id for route in extra[1])

        routes = list({route.route_id: route for route in routes}.values())
        result = (self._portfolio_expected_turns(routes), routes)
        self._ticket_plan_cache[cache_key] = result
        return result

    def _replan(self):
        """Recompute the planned route set for every unscored ticket.

        Runs fresh on the current culled map each time, which is what
        "update the planned route to account for being cut off" means in
        practice: routes another player took simply no longer exist here.
        The first two tickets get an exact joint Steiner tree; any further
        tickets attach greedily with already-planned routes free.
        """
        if self._replan_result is not None:
            return self._replan_result
        culled = self._culled()
        unscored = self._unscored_tickets()
        plan = self._plan_for_tickets(culled, unscored)
        routes = [] if plan is None else plan[1]

        self._planned_routes = routes
        self._planned_route_ids = {route.route_id for route in routes}
        self._replan_result = routes
        return self._replan_result

    @staticmethod
    def _culled_without_route(culled, route_id: str):
        return replace(culled, routes=[route for route in culled.routes if route.route_id != route_id])

    def _route_pressure(self, route: Route) -> float:
        """Expected-turn penalty if this planned route is lost right now."""
        if route.route_id in self._route_pressure_cache:
            return self._route_pressure_cache[route.route_id]
        if route.route_id not in self._planned_route_ids:
            return 0.0
        tickets = self._unscored_tickets()
        if not tickets:
            return 0.0

        culled = self._culled()
        baseline = self._plan_for_tickets(culled, tickets)
        if baseline is None:
            return 0.0
        alternative = self._plan_for_tickets(self._culled_without_route(culled, route.route_id), tickets)
        if alternative is None:
            pressure = float("inf")
        else:
            pressure = max(0.0, alternative[0] - baseline[0])
        self._route_pressure_cache[route.route_id] = pressure
        return pressure

    def _blocking_readiness(self, route: Route) -> float:
        """Public-information estimate that an opponent can claim next turn."""
        options = route.payment_colors()
        best = 0.0
        for opponent in self._view.opponents:
            visible_match = opponent.exposed_hand.get("L", 0)
            if options:
                visible_match += max(
                    (opponent.exposed_hand.get(color, 0) for color in options),
                    default=0,
                )
            visible_ratio = min(1.0, visible_match / max(1, route.length))
            hand_ratio = min(1.0, opponent.num_cards_in_hand / max(1, route.length))
            best = max(best, 0.65 * hand_ratio + 0.35 * visible_ratio)
        return best

    def _route_urgency(self, route: Route) -> float:
        pressure = self._route_pressure(route)
        if pressure == float("inf"):
            return float("inf")
        return self._blocking_readiness(route) * (1.0 + pressure)

    def _claim_priority(self, route: Route):
        pressure = self._route_pressure(route)
        critical = (
            pressure == float("inf")
            or pressure >= self._CRITICAL_ROUTE_PRESSURE
        )
        return (
            critical,
            self._route_urgency(route),
            pressure,
            self._route_points(route),
            route.length,
        )

    def _card_needs(self):
        """Remaining portfolio quotas after jointly allocating held wilds."""
        deficits, locomotive_deficit = self._portfolio_deficits(
            self._planned_routes, self._view.hand, self._view.face_up_cards
        )
        needs = {color: deficits[color] for color in self._CARD_COLORS}
        needs["L"] = locomotive_deficit
        return needs

    def _claimable_planned(self, affordable):
        """Affordable routes belonging to the current portfolio."""
        return [
            (route, locomotives) for route, locomotives in affordable
            if route.route_id in self._planned_route_ids
        ]

    def _score_route_pick(self, claimable_routes: 'List[tuple[Route, int]]') -> 'tuple[Route, int]':
        return max(
            claimable_routes,
            key=lambda pick: (self._route_points(pick[0]), pick[0].length, -pick[1]),
        )

    def _late_game_pressure(self, view) -> bool:
        return (
            view.trains_remaining <= self._LATE_GAME_TRAINS
            or any(opponent.remaining_trains <= self._OPPONENT_ENDGAME_TRAINS for opponent in view.opponents)
        )

    def _should_claim_points_before_tickets(self, view, claims) -> bool:
        if not claims:
            return False
        if view.tickets_in_deck < 3:
            return True
        if not self._late_game_pressure(view):
            return False
        route, _ = self._score_route_pick(self._picks_from_claims(view, claims))
        return self._route_points(route) >= self._OPPORTUNITY_MIN_POINTS

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
            self._replan()
            if claims and self._should_claim_points_before_tickets(view, claims):
                return self._claim_action(view, claims)
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

    def _planned_claim_key(self, action):
        """One-step Bellman value after paying this exact legal action."""
        route = self._view.route_by_id(action.route_id)
        hand_after = Counter(self._view.hand)
        hand_after.subtract(claim_spend(action, route))
        hand_after = +hand_after
        remaining = [
            planned for planned in self._planned_routes
            if planned.route_id != route.route_id
        ]
        future_turns = self._portfolio_expected_turns(remaining, hand_after)
        pressure = self._route_pressure(route)
        critical = pressure == float("inf") or pressure >= self._CRITICAL_ROUTE_PRESSURE
        urgency = self._route_urgency(route)
        risk_credit = 50.0 if urgency == float("inf") else min(50.0, urgency)
        return (
            not critical,
            future_turns - risk_credit,
            action.locomotives,
            action.color,
            action.payment or (),
        )

    def _claim_action(self, view, claims):
        self._replan()
        planned_actions = [
            action for action in claims
            if action.route_id in self._planned_route_ids
        ]
        if planned_actions:
            return min(planned_actions, key=self._planned_claim_key)

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
            return max(planned, key=lambda pick: self._claim_priority(pick[0]))

        if not self._unscored_tickets():
            return self._score_route_pick(claimable_routes)

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
        """Lowest expected portfolio turns after this exact card decision."""
        self._replan()
        if not self._planned_routes:
            for action in draw_actions:
                if isinstance(action, DrawBlind):
                    return action
            return draw_actions[0]

        hand = Counter(view.hand)
        face_up = list(view.face_up_cards)

        def after_card(color):
            next_hand = Counter(hand)
            next_hand[color] += 1
            return next_hand

        def action_value(action):
            if isinstance(action, DrawFaceUp):
                next_face_up = list(face_up)
                next_face_up.remove(action.card)
                value = self._portfolio_expected_turns(
                    self._planned_routes,
                    after_card(action.card),
                    next_face_up,
                )
                # A visible locomotive ends the drawing turn after one card.
                if action.card == "L" and view.decision != "draw_second":
                    value += 0.5
                return value
            if isinstance(action, DrawBlind) and self._odds:
                return sum(
                    probability * self._portfolio_expected_turns(
                        self._planned_routes, after_card(color), face_up
                    )
                    for color, probability in self._odds.items()
                )
            return float("inf")

        return min(
            draw_actions,
            key=lambda action: (
                action_value(action),
                0 if isinstance(action, DrawBlind) else 1,
                getattr(action, "card", ""),
            ),
        )

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

    from notebook_harness.game_runner import initialize_game, list_maps

    mo.md("# Codex Best Bot — spectate & debug").left()
    return initialize_game, list_maps, mo


@app.cell(hide_code=True)
def _(list_maps, mo):
    from notebook_harness.game_runner import available_bots

    # Every bot notebook on disk, plus this notebook's live class so edits
    # made here take effect without reloading.
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[BOT_META["name"]] = CodexBestBot

    map_picker = mo.ui.dropdown(options=list_maps(), value=list_maps()[0], label="Map")
    seat_pickers = mo.ui.array(
        [
            mo.ui.dropdown(
                options=bot_options,
                value=BOT_META["name"] if index < 2 else "(empty)",
                label=f"Seat {index + 1}",
            )
            for index in range(5)
        ]
    )
    mo.hstack([map_picker, seat_pickers], align="start", justify="start")
    return map_picker, seat_pickers


@app.cell(hide_code=True)
def _(initialize_game, map_picker, mo, seat_pickers):
    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(len(seated_bot_classes) < 2, mo.md("Pick bots for at least two seats to run a game."))
    harness_game = initialize_game(
        [bot_class() for bot_class in seated_bot_classes], map_name=map_picker.value
    )
    harness_game.play()
    return (harness_game,)


@app.cell(hide_code=True)
def _(harness_game, mo):
    # Created once per game (not per slider step) so the force simulation
    # keeps running instead of restarting from scratch on every step.
    from wigglystuff import PlaySlider

    from notebook_harness.info_bar_widget import InfoBarWidget
    from notebook_harness.player_list_widget import PlayerListWidget
    from notebook_harness.route_graph_widget import RouteGraphWidget, build_graph_data

    initial_nodes, initial_edges = harness_game.board_at(0)
    graph = mo.ui.anywidget(RouteGraphWidget(data=build_graph_data(initial_nodes, initial_edges)))
    player_list = mo.ui.anywidget(PlayerListWidget(players=harness_game.roster()))
    info_bar = mo.ui.anywidget(InfoBarWidget(market=harness_game.market_at(0)))
    # Must be created in a different cell than the one reading its value:
    # marimo never re-runs a UI element's defining cell on interaction, so a
    # same-cell read would freeze the map at step 0. It still *displays* in
    # the layout cell below.
    step_slider = mo.ui.anywidget(
        PlaySlider(min_value=0, max_value=harness_game.snapshot_count() - 1, step=1, interval_ms=300)
    )
    return build_graph_data, graph, info_bar, player_list, step_slider


@app.cell(hide_code=True)
def _(
    build_graph_data,
    graph,
    harness_game,
    info_bar,
    mo,
    player_list,
    step_slider,
):
    # Pushes each step's board state into the existing widget instance
    # instead of constructing a new one, so node positions persist across
    # steps and only the diff (newly claimed routes) animates.
    # Selecting a player in the list switches to their culled view: their
    # network merged into single nodes, showing only routes they could still
    # claim (that topology change intentionally restarts the simulation).
    viewpoint = player_list.value["selected_player"] or None
    step = int(step_slider.value["value"])
    nodes, edges = harness_game.board_at(step, viewpoint)
    graph.data = build_graph_data(nodes, edges)
    # Market follows the same step + selection: spectator sees the true draw
    # pile; a selected player sees their public-information odds pool.
    info_bar.market = harness_game.market_at(step, viewpoint)
    mo.vstack([step_slider, mo.hstack([graph, player_list], align="start", justify="start"), info_bar])
    return


if __name__ == "__main__":
    app.run()
