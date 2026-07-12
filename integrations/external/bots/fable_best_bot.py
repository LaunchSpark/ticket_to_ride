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
        "id": "fable_best_bot",
        "name": "Fable Best Bot",
        "version": "1.0.0",
        "description": "Kitchen-sink heuristic bot: turn-cost planning, endgame clock, contention-aware claims.",
        "author": "Claude Fable 5",
        "tags": ["example", "strong"],
    }


@app.class_definition(hide_code=True)
class FableBestBot(ActionBot):
    """Every non-ML improvement in one bot.

    Built on the ExampleBot/QualifierBot chassis (exact <=4-terminal
    Steiner planning over the culled map, expected-turns route costs from
    public information) and adds:

    - an endgame clock: estimates the own turns remaining from every
      player's train-spend pace, stops drawing tickets late, abandons
      tickets that can't finish in time, and cashes out board points when
      drawing can no longer pay off;
    - contention-aware claiming: doubles in 2-3 player games and routes
      touching opponent networks are priced up in planning and claimed
      first once affordable;
    - a locomotive economy: held locomotives plug deficits in the cost
      model at an option-value premium, get spent on long/contested/
      endgame claims instead of only the single longest planned route,
      and a face-up locomotive is taken when it beats two mediocre picks;
    - disciplined ticket drawing: only with everything scored and a long
      clock, with feasibility checks in both trains and turns and
      nearly-free-only keeps late;
    - denial-aware market picks: ties break toward cards the score leader
      is visibly collecting;
    - network gravity: value claims prefer routes touching the own
      network (longest-path bonus and free future travel).
    """

    META = BOT_META

    # Route points by length (kept for claim *worth*; costs are in turns).
    _ROUTE_POINTS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 10, 6: 15, 7: 18, 8: 21}
    _CARD_COLORS = ["R", "B", "U", "G", "O", "P", "W", "Y"]

    # --- tunables -----------------------------------------------------
    # Closure risk for half of a double route in a 2-3 player game.
    _DOUBLE_ROUTE_RISK = 1.4
    # Milder risk for routes touching an opponent's network endpoints.
    _CONTESTED_RISK = 1.15
    # Turns-equivalent option value burned per locomotive planned into a
    # deficit (a held wild is worth keeping flexible).
    _LOCO_OPTION_COST = 0.35
    # Locomotives may be spent on claims at least this long (always
    # allowed in the endgame or on contested routes).
    _LOCO_SPEND_MIN_LENGTH = 4
    # A third initial ticket rides along if it adds at most this many
    # expected turns once the pair's tree is free.
    _EXTRA_TICKET_MAX_COST = 3.0
    # Endgame trigger: estimated own turns remaining.
    _ENDGAME_TURNS = 8.0
    # Never draw tickets with fewer estimated turns left than this.
    _TICKET_MIN_TURNS = 11.0
    # Turns-per-train proxy when judging whether a ticket can still finish.
    _TICKET_TURNS_PER_TRAIN = 0.8
    # Late keeps (clock under TICKET_MIN + 4) must attach almost for free.
    _LATE_KEEP_MAX_COST = 1.5
    # Planning may trade expected turns for route points (edge weight =
    # cost - value*points). Zero keeps the metric honest: distorting it
    # corrupts ticket ratios and feasibility judgments (measured -20%
    # win rate at 0.2), so express value preferences in claim order, not
    # in the path metric.
    _POINT_VALUE_TURNS = 0.0
    # Mid-game ticket keeps must attach at no more than this many expected
    # turns per point (10 = effectively off: the ratio filter measured as a
    # net loss — it starved completed-ticket points more than it saved in
    # penalties), and never cost more than a third of the clock.
    _KEEP_MAX_RATIO = 10.0

    def __init__(self) -> None:
        super().__init__()
        self._planned_routes: 'List[Route]' = []
        self._planned_route_ids: 'set[str]' = set()

    # ------------------------------------------------------------------
    # Per-decision state
    # ------------------------------------------------------------------

    def act(self, view, legal_actions):
        self._prime_view(view)
        if view.decision == "keep_tickets":
            return self._keep_action(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw_action(view, legal_actions)
        return self._turn_action(view, legal_actions)

    def _prime_view(self, view) -> None:
        """Cache the lookups every cost/policy call this decision shares."""
        self._view = view
        self._odds = view.draw_odds()
        self._siblings_by_key = {}
        for route in view.routes:
            self._siblings_by_key.setdefault(route.sibling_group_key(), []).append(route)

        self._own_cities: 'set[str]' = set()
        self._opponent_cities: 'set[str]' = set()
        for route_id, owner in view.claimed_by.items():
            route = view.route_by_id(route_id)
            cities = self._own_cities if owner == view.player_id else self._opponent_cities
            cities.add(route.city1)
            cities.add(route.city2)

        self._turns_left = self._estimate_turns_left(view)
        self._endgame = self._turns_left <= self._ENDGAME_TURNS

    @staticmethod
    def _estimate_turns_left(view) -> float:
        """Estimated own turns before someone triggers the final round.

        Every player's train-spend pace so far (with a modest floor, since
        everyone accelerates once their plan is assembled) says how many of
        our turns remain until they hit two trains; the game ends on the
        fastest clock, plus the one final-round turn.
        """
        seats = [(view.trains_remaining,)] + [(o.remaining_trains,) for o in view.opponents]
        own_turns_so_far = max(1.0, view.turn_number / max(1, len(view.opponents) + 1))
        fastest = None
        for (trains,) in seats:
            pace = max((45 - trains) / own_turns_so_far, 1.2)
            turns = max(0.0, (trains - 2) / pace)
            fastest = turns if fastest is None else min(fastest, turns)
        return (fastest or 0.0) + 1.0

    # ------------------------------------------------------------------
    # Cost model: risk-adjusted expected turns to assemble and claim
    # ------------------------------------------------------------------

    def _route_cost(self, route: Route) -> float:
        """Expected turns to make this route claimable and claim it.

        Matching face-up cards are certain picks; the rest arrive at the
        unknown-pool odds (blind locomotives count toward any color) at ~2
        picks per drawing turn. Held locomotives may plug deficit slots at
        an option-value premium. Gray routes price at their cheapest
        color. The claim turn is added, then contention scales the total:
        doubles in small games hardest, opponent-adjacent routes mildly.
        Infinity = not assemblable from public information.
        """
        view = self._view
        hand = view.hand
        locomotive_odds = self._odds.get("L", 0.0)
        locomotives_held = hand.get("L", 0)

        colors = [route.color] if route.color != "X" else self._CARD_COLORS
        best_turns = None
        for color in colors:
            deficit = route.length - hand.get(color, 0)
            if deficit <= 0:
                best_turns = 0.0
                break
            certain = min(deficit, view.face_up_cards.count(color))
            pick_odds = self._odds.get(color, 0.0) + locomotive_odds
            loco_options = (0, min(locomotives_held, deficit)) \
                if self._may_spend_locomotives(route) else (0,)
            for spent_locos in loco_options:
                remaining = deficit - spent_locos - min(certain, deficit - spent_locos)
                usable_certain = min(certain, deficit - spent_locos)
                if remaining > 0 and pick_odds <= 0.0:
                    continue
                expected_picks = usable_certain + (remaining / pick_odds if remaining else 0.0)
                turns = expected_picks / 2 + spent_locos * self._LOCO_OPTION_COST
                if best_turns is None or turns < best_turns:
                    best_turns = turns
        if best_turns is None:
            return float("inf")

        cost = best_turns + 1.0  # the claim turn itself
        cost *= self._contention_risk(route)
        return cost

    def _contention_risk(self, route: Route) -> float:
        siblings = self._siblings_by_key.get(route.sibling_group_key(), [route])
        if len(siblings) > 1 and self._view.player_count <= 3:
            return self._DOUBLE_ROUTE_RISK
        if route.city1 in self._opponent_cities or route.city2 in self._opponent_cities:
            return self._CONTESTED_RISK
        return 1.0

    def _route_points(self, route: Route) -> int:
        return self._ROUTE_POINTS.get(route.length, route.length)

    # ------------------------------------------------------------------
    # Pathfinding over the culled map (expected-turn weights)
    # ------------------------------------------------------------------

    def _culled(self):
        return self._view.culled_map()

    def _plan_weight(self, route: Route) -> float:
        """Planning weight: expected turns net of the points the route pays
        back. Clamped positive so Dijkstra stays valid; long routes get
        cheap, not free."""
        cost = self._route_cost(route)
        if cost == float("inf"):
            return cost
        return max(0.05, cost - self._POINT_VALUE_TURNS * self._route_points(route))

    def _adjacency(self, culled, free_route_ids: 'Collection[str]' = frozenset()):
        """node -> [(neighbor, cost, route)] with planned/free routes at cost 0."""
        adjacency = {}
        for route in culled.routes:
            node_a, node_b = culled.endpoints(route)
            cost = 0 if route.route_id in free_route_ids else self._plan_weight(route)
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
                0 if route.route_id in free_route_ids else self._plan_weight(route)
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

    def _active_tickets(self):
        """Unscored tickets still worth chasing: completable in the trains
        we hold AND the turns the clock says we have. A hopeless ticket's
        penalty is already sunk; spending turns on it just loses twice."""
        culled = self._culled()
        active = []
        for ticket in self._unscored_tickets():
            trains = culled.cheapest_connection(ticket.city1, ticket.city2)
            if trains is None or trains > self._view.trains_remaining:
                continue
            if trains * self._TICKET_TURNS_PER_TRAIN > self._turns_left + 1:
                continue
            active.append(ticket)
        return active

    def _replan(self):
        """Recompute the planned route set for every active ticket.

        Runs fresh on the current culled map each time: routes another
        player took no longer exist here, and tickets the clock has killed
        drop out of the plan. The first two tickets get an exact joint
        Steiner tree; any further tickets attach greedily with
        already-planned routes free.
        """
        culled = self._culled()
        active = self._active_tickets()

        routes: 'List[Route]' = []
        free: 'set[str]' = set()

        head, tail = active[:2], active[2:]
        if head:
            cities = [city for ticket in head for city in (ticket.city1, ticket.city2)]
            joint = self._steiner_tree(culled, cities)
            if joint is None:
                tail = active[1:]
                head = active[:1]
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

    def _plan_remaining_cost(self) -> float:
        """Expected drawing turns still needed to afford the whole plan."""
        return sum(max(0.0, self._route_cost(route) - 1.0) for route in self._planned_routes)

    def _card_needs(self):
        """Deficit per color under the current plan.

        Grey demand is paid in one color, so only the single largest
        surplus covers it; any grey deficit is assigned to the color with
        the biggest surplus (fewest extra draws to stack). Locomotives
        reduce the longest planned route's color demand first.
        """
        reserved: 'Counter[str]' = Counter()
        grey_needed = 0
        for route in self._planned_routes:
            if route.color == "X":
                grey_needed += route.length
            else:
                reserved[route.color] += route.length

        hand = self._view.hand
        deficits = {c: max(0, reserved[c] - hand.get(c, 0)) for c in self._CARD_COLORS}
        surplus = {c: max(0, hand.get(c, 0) - reserved[c]) for c in self._CARD_COLORS}

        stack_color = max(self._CARD_COLORS, key=lambda c: surplus[c])
        grey_deficit = max(0, grey_needed - surplus[stack_color])
        if grey_deficit:
            deficits[stack_color] += grey_deficit

        locomotives = hand.get("L", 0)
        if locomotives and self._planned_routes:
            longest = max(self._planned_routes, key=lambda route: route.length)
            target = stack_color if longest.color == "X" else longest.color
            deficits[target] = max(0, deficits[target] - locomotives)
        return deficits

    def _claimable_planned(self, picks):
        """Affordable planned routes, honoring the locomotive policy:
        locomotives get spent on long, contested, or endgame claims —
        cheap uncontested routes wait for colored cards instead."""
        chosen = []
        for route, locomotives in picks:
            if route.route_id not in self._planned_route_ids:
                continue
            if locomotives > 0 and not self._may_spend_locomotives(route):
                continue
            chosen.append((route, locomotives))
        return chosen

    def _may_spend_locomotives(self, route: Route) -> bool:
        return (
            route.length >= self._LOCO_SPEND_MIN_LENGTH
            or self._endgame
            or self._contention_risk(route) > 1.0
        )

    # ------------------------------------------------------------------
    # Engine-facing decisions
    # ------------------------------------------------------------------

    def _turn_action(self, view, legal_actions):
        claims = [a for a in legal_actions if isinstance(a, ClaimRoute)]
        draws = [a for a in legal_actions if isinstance(a, (DrawBlind, DrawFaceUp))]
        tickets_offered = any(isinstance(a, DrawTickets) for a in legal_actions)

        self._replan()
        picks = self._picks_from_claims(view, claims)
        planned_picks = self._claimable_planned(picks)

        # 1. A planned route we can afford: take it before someone else does.
        if planned_picks:
            return self._claim_action(view, claims, planned_picks)

        # 2. Everything is scored and the clock is long: invest in more
        #    tickets. (Proactive draws while a plan was still in flight
        #    measured as the variance engine behind the worst blowouts.)
        wants_tickets = (
            tickets_offered
            and not self._endgame
            and self._turns_left > self._TICKET_MIN_TURNS
            and not self._active_tickets()
        )
        if wants_tickets:
            return DrawTickets()

        # 3. Endgame cash-out: when drawing can't pay off anymore, convert
        #    the hand into board points (network-adjacent, longest first).
        if claims and self._endgame and self._should_cash_out(picks):
            return self._claim_action(view, claims, picks)

        # 4. Otherwise draw toward the plan.
        if draws:
            return self._draw_action(view, draws)

        # 5. Forced fallbacks: deck dry -> claim; else tickets; else pass.
        if claims:
            return self._claim_action(view, claims, picks)
        if tickets_offered:
            return DrawTickets()
        return legal_actions[0]

    def _should_cash_out(self, picks) -> bool:
        """In the endgame, claim now unless one more drawing turn plausibly
        completes a planned route worth more than the best claim today."""
        if self._turns_left <= 2.0:
            return True
        best_now = max((self._route_points(route) for route, _ in picks), default=0)
        if not self._planned_routes:
            return best_now > 0
        if self._plan_remaining_cost() > self._turns_left:
            return best_now >= 2  # the whole plan can't finish: bank points
        cheapest_planned = min(self._route_cost(route) for route in self._planned_routes)
        planned_reachable = cheapest_planned <= self._turns_left - 1
        return not planned_reachable and best_now >= 2

    @staticmethod
    def _picks_from_claims(view, claims):
        """(route, locomotives) picks — one per route at its minimum
        locomotive spend."""
        best = {}
        for action in claims:
            current = best.get(action.route_id)
            if current is None or action.locomotives < current[1]:
                best[action.route_id] = (view.route_by_id(action.route_id), action.locomotives)
        return list(best.values())

    def _claim_action(self, view, claims, picks=None):
        picks = picks if picks is not None else self._picks_from_claims(view, claims)
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

    def _choose_route_pick(self, picks):
        """Planned routes first (contested before comfortable, then most
        valuable); otherwise the best value claim, preferring routes that
        touch the own network; forced dumps spend the least-needed cards
        on the shortest gray route."""
        planned = self._claimable_planned(picks)
        if planned:
            # risk-weighted worth: a contested route gains urgency in
            # proportion to its value, never ahead of a much bigger claim
            return max(
                planned,
                key=lambda pick: self._route_points(pick[0]) * self._contention_risk(pick[0]),
            )

        if self._endgame:
            valuable = [pick for pick in picks if pick[1] == 0 or self._may_spend_locomotives(pick[0])]
            if valuable:
                return max(valuable, key=lambda pick: self._claim_value(pick[0]))

        # Forced claim (train deck dry): spend what the plan values least.
        needs = self._card_needs()
        options = [pick for pick in picks if pick[1] == 0] or list(picks)
        gray = [pick for pick in options if pick[0].color == "X"]
        if gray:
            return min(gray, key=lambda pick: pick[0].length)
        return min(options, key=lambda pick: (needs.get(pick[0].color, 0), pick[0].length))

    def _claim_value(self, route: Route) -> float:
        """Board points plus a nudge for growing the own network (longest
        path bonus, free future travel)."""
        bonus = 1.5 if (route.city1 in self._own_cities or route.city2 in self._own_cities) else 0.0
        return self._route_points(route) + bonus

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_action(self, view, draw_actions):
        """Best single pick against the live market.

        Needed colors first (biggest deficit; ties break toward denying
        the score leader's visible collection). A face-up locomotive is
        taken when it makes a planned route affordable outright or when
        the two regular picks it forfeits are likely worth less than one
        wild card. Otherwise hit the deck.
        """
        self._replan()
        needs = self._card_needs()

        face_ups = [a for a in draw_actions if isinstance(a, DrawFaceUp)]
        useful = [a for a in face_ups if a.card != "L" and needs.get(a.card, 0) > 0]
        locomotive_pick = next((a for a in face_ups if a.card == "L"), None)

        if locomotive_pick is not None and self._locomotive_worth_taking(useful, needs):
            return locomotive_pick
        if useful:
            leader_wants = self._leader_collection()
            return max(
                useful,
                key=lambda a: (needs[a.card], 1 if a.card in leader_wants else 0),
            )
        for action in draw_actions:
            if isinstance(action, DrawBlind):
                return action
        return draw_actions[0]

    def _locomotive_worth_taking(self, useful, needs) -> bool:
        """A face-up L costs the second pick: worth it when it completes a
        planned route's budget now, or when regular picks are near-blanks."""
        hand = self._view.hand
        wilds = hand.get("L", 0)
        for route in self._planned_routes:
            colors = [route.color] if route.color != "X" else self._CARD_COLORS
            best_deficit = min(route.length - hand.get(c, 0) for c in colors)
            if best_deficit - wilds == 1 and self._may_spend_locomotives(route):
                return True  # this single wild makes the route affordable
        if useful:
            return False
        pick_quality = sum(self._odds.get(c, 0.0) for c, d in needs.items() if d > 0)
        pick_quality += self._odds.get("L", 0.0)
        return pick_quality < 0.5  # two blanks-ish picks lose to one wild

    def _leader_collection(self) -> 'set[str]':
        """Colors the current score leader is visibly stacking (2+ exposed)."""
        opponents = self._view.opponents
        if not opponents:
            return set()
        leader = max(opponents, key=lambda o: o.score)
        return {color for color, count in leader.exposed_hand.items() if count >= 2 and color != "L"}

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------

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
        """Initial offer: keep the pair with the best turn-cost/points
        ratio, plus a third if it rides along cheaply. Later offers: keep
        everything the network already spans (free points) plus the best
        attachable ticket that the clock still allows. Forced keeps take
        the lowest value to minimize the penalty."""
        culled = self._culled()

        keep = [t for t in offer if culled.connected(t.city1, t.city2)]  # free points
        candidates = [t for t in offer if t not in keep]
        viable = []
        for ticket in candidates:
            trains = culled.cheapest_connection(ticket.city1, ticket.city2)
            if trains is None or trains > self._view.trains_remaining:
                continue
            if trains * self._TICKET_TURNS_PER_TRAIN > self._turns_left:
                continue
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
                if attachment[0] > self._turns_left / 3:
                    continue  # too big a bite out of the remaining clock
                late = self._turns_left < self._TICKET_MIN_TURNS + 4
                if late and attachment[0] > self._LATE_KEEP_MAX_COST:
                    continue  # late keeps must be nearly free
                ratio = attachment[0] / ticket.value
                if ratio > self._KEEP_MAX_RATIO:
                    continue  # points too expensive: pass unless forced
                if best is None or ratio < best[0] or (ratio == best[0] and ticket.value > best[1].value):
                    best = (ratio, ticket)
            if best is not None:
                keep.append(best[1])

        if not keep:
            keep = [min(offer, key=lambda ticket: ticket.value)]
        return keep

    def _pick_initial_tickets(self, culled, viable):
        """Best turn-cost/points pair by exact Steiner tree, plus a cheap third."""
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

    mo.md("# Fable Best Bot — spectate & debug").left()
    return initialize_game, list_maps, mo


@app.cell(hide_code=True)
def _(list_maps, mo):
    from notebook_harness.game_runner import available_bots

    # Every bot notebook on disk, plus this notebook's live class so edits
    # made here take effect without reloading.
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[BOT_META["name"]] = FableBestBot

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
