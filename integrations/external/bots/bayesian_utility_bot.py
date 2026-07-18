import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup(hide_code=True):
    import csv
    import heapq
    import math
    from collections import Counter
    from itertools import combinations

    from external.contracts.base_bot import ActionBot
    from ticket_to_ride.engine.actions import (
        ClaimRoute,
        DrawBlind,
        DrawFaceUp,
        DrawTickets,
        KeepTickets,
        Pass,
        claim_spend,
    )
    from ticket_to_ride.engine.game import Game
    from ticket_to_ride.engine.state.decks import DestinationTicket, resolve_tickets_path
    from ticket_to_ride.engine.state.map import Route, contract_map

    BOT_META = {
        "schema_version": 1,
        "id": "bayesian_utility_bot",
        "name": "Bayesian Utility Bot",
        "version": "1.0.0",
        "description": "First-principles expected-utility player with public-information Bayesian inference.",
        "author": "OpenAI Codex",
        "tags": ["bayesian", "game-theory", "expected-utility"],
    }


@app.class_definition(hide_code=True)
class BayesianUtilityBot(ActionBot):
    """Choose the legal move with the greatest posterior expected utility.

    There is no stored route plan and no strategy inherited from another
    bot. Every decision is recomputed from the legal menu and a common state
    value. The value contains expected terminal ticket payoff, future route
    options, network option value, and longest-path equity. Claims apply
    their exact payment and board transition. Visible draws are deterministic;
    blind draws integrate over ``PlayerView.unknown_pool``. Opponent route
    races use the finite-pool hypergeometric posterior for each hidden hand,
    updated by public face-up cards and claimed-network evidence.
    """

    META = BOT_META

    _COLORS = ("R", "B", "U", "G", "O", "P", "W", "Y")
    _DRAW_PICKS_PER_TURN = 1.85
    _ROUTE_OPTION_WEIGHT = 0.16
    _NETWORK_PAIR_VALUE = 0.075
    _TRAIN_SHADOW_PRICE = 0.14
    _CLAIM_TRAIN_OPPORTUNITY = 1.25
    _BLOCK_HAZARD_WEIGHT = 2.2
    _DENIAL_WEIGHT = 0.30
    _TICKET_TIME_DISCOUNT = 0.10
    _MAX_PAYMENT_STATES = 128

    def __init__(self) -> None:
        super().__init__()
        self._ticket_prior_map = None
        self._ticket_prior = []

    # ------------------------------------------------------------------
    # Public decision interface
    # ------------------------------------------------------------------

    def act(self, view, legal_actions):
        self._prepare(view)
        if view.decision == "keep_tickets":
            return max(
                legal_actions,
                key=lambda action: self._keep_utility(action),
            )

        base = self._state_utility(view.hand, view.claimed_by, view.trains_remaining)
        ranked = [
            (self._action_utility(action, base), -index, action)
            for index, action in enumerate(legal_actions)
        ]
        return max(ranked, key=lambda item: (item[0], item[1]))[2]

    def _prepare(self, view) -> None:
        self._view = view
        self._odds = view.draw_odds()
        self._unknown = view.unknown_pool()
        self._routes_by_id = {route.route_id: route for route in view.routes}
        self._siblings = {}
        for route in view.routes:
            self._siblings.setdefault(route.sibling_group_key(), []).append(route)
        self._state_cache = {}
        self._hand_key_cache = {}
        self._claim_key_cache = {}
        self._contract_cache = {}
        self._projection_cache = {}
        self._ticket_path_cache = {}
        self._portfolio_path_cache = {}
        self._payment_cache = {}
        self._turn_cost_cache = {}
        self._block_cache = {}
        self._opponent_components = {
            opponent.player_id: [set(component) for component in view.claim_components(opponent.player_id)]
            for opponent in view.opponents
        }
        self._load_ticket_prior()
        self._build_option_frontier()

    def _hand_key(self, hand) -> tuple:
        identity = id(hand)
        cached = self._hand_key_cache.get(identity)
        if cached is not None and cached[0] is hand:
            return cached[1]
        key = tuple(sorted(
            (color, int(count)) for color, count in hand.items() if count > 0
        ))
        # Keep the object alive for this decision so Python cannot recycle
        # its id for a different successor Counter.
        self._hand_key_cache[identity] = (hand, key)
        return key

    def _claim_key(self, claimed_by) -> tuple:
        identity = id(claimed_by)
        cached = self._claim_key_cache.get(identity)
        if cached is not None and cached[0] is claimed_by:
            return cached[1]
        key = tuple(sorted(claimed_by.items()))
        self._claim_key_cache[identity] = (claimed_by, key)
        return key

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 40:
            return 1.0
        if value <= -40:
            return 0.0
        return 1.0 / (1.0 + math.exp(-value))

    # ------------------------------------------------------------------
    # Legal-action expected utility
    # ------------------------------------------------------------------

    def _action_utility(self, action, base: float) -> float:
        if isinstance(action, ClaimRoute):
            route = self._routes_by_id[action.route_id]
            hand = Counter(self._view.hand)
            hand.subtract(claim_spend(action, route))
            hand = +hand
            claimed_by = dict(self._view.claimed_by)
            claimed_by[route.route_id] = self._view.player_id
            trains = self._view.trains_remaining - route.length
            continuation = self._state_utility(hand, claimed_by, trains)
            route_points = Game.SCORE_TABLE.get(route.length, route.length)
            denial = (
                self._DENIAL_WEIGHT
                * route_points
                * self._block_probability(route)
            )
            return (
                route_points
                - self._CLAIM_TRAIN_OPPORTUNITY * route.length
                + continuation
                - base
                + denial
            )

        if isinstance(action, DrawFaceUp):
            hand = Counter(self._view.hand)
            hand[action.card] += 1
            if self._view.decision == "draw_second" or action.card == "L":
                return self._state_utility(
                    hand, self._view.claimed_by, self._view.trains_remaining
                ) - base
            remaining_market = list(self._view.face_up_cards)
            if 0 <= action.index < len(remaining_market):
                remaining_market.pop(action.index)
            return self._best_second_state(hand, remaining_market) - base

        if isinstance(action, DrawBlind):
            if not self._odds:
                return -1e9
            expected = 0.0
            for color, probability in self._odds.items():
                hand = Counter(self._view.hand)
                hand[color] += 1
                if self._view.decision == "draw_second":
                    terminal = self._state_utility(
                        hand, self._view.claimed_by, self._view.trains_remaining
                    )
                else:
                    terminal = self._best_second_state(hand, self._view.face_up_cards)
                expected += probability * terminal
            return expected - base

        if isinstance(action, DrawTickets):
            return self._ticket_offer_expected_utility()

        if isinstance(action, Pass):
            return 0.0
        return -1e9

    def _best_second_state(self, hand, market) -> float:
        values = []
        if self._odds:
            values.append(sum(
                probability * self._state_utility(
                    Counter(hand) + Counter({color: 1}),
                    self._view.claimed_by,
                    self._view.trains_remaining,
                )
                for color, probability in self._odds.items()
            ))
        for color in market:
            if color == "L":
                continue
            values.append(self._state_utility(
                Counter(hand) + Counter({color: 1}),
                self._view.claimed_by,
                self._view.trains_remaining,
            ))
        return max(values, default=self._state_utility(
            hand, self._view.claimed_by, self._view.trains_remaining
        ))

    # ------------------------------------------------------------------
    # State value
    # ------------------------------------------------------------------

    def _state_utility(self, hand, claimed_by, trains_remaining: int) -> float:
        key = (self._hand_key(hand), self._claim_key(claimed_by), trains_remaining)
        cached = self._state_cache.get(key)
        if cached is not None:
            return cached

        tickets = self._ticket_set_utility(
            self._view.tickets, hand, claimed_by, trains_remaining
        )
        route_options = self._route_option_value(hand, claimed_by, trains_remaining)
        network = self._network_value(claimed_by)
        longest = self._longest_path_equity(claimed_by)
        value = tickets + route_options + network + longest
        self._state_cache[key] = value
        return value

    def _contracted(self, claimed_by):
        key = self._claim_key(claimed_by)
        cached = self._contract_cache.get(key)
        if cached is None:
            cached = contract_map(
                self._view.routes,
                self._view.player_count,
                claimed_by,
                self._view.player_id,
                siblings_by_key=self._siblings,
            )
            self._contract_cache[key] = cached
        return cached

    def _route_option_value(self, hand, claimed_by, trains_remaining: int) -> float:
        if trains_remaining <= 0:
            return 0.0
        trigger = min(
            [trains_remaining, *(opponent.remaining_trains for opponent in self._view.opponents)]
        )
        # These are options *after* the action currently under evaluation.
        # Once somebody has triggered the last round there is no later turn
        # in which to realize them. Earlier, scale smoothly by the number of
        # plausible future claim cycles rather than valuing four forever.
        horizon_scale = min(1.0, max(0.0, (trigger - 2) / 10.0))
        if horizon_scale == 0.0:
            return 0.0
        candidates = []
        for route in self._contracted(claimed_by).routes:
            if route.route_id not in self._option_route_ids:
                continue
            if route.length > trains_remaining:
                continue
            turns = self._route_acquisition_turns(route, hand)
            if not math.isfinite(turns):
                continue
            points = Game.SCORE_TABLE.get(route.length, route.length)
            candidates.append((points + 0.12 * route.length) / (turns ** 0.78))
        candidates.sort(reverse=True)
        return horizon_scale * self._ROUTE_OPTION_WEIGHT * sum(candidates[:4])

    def _build_option_frontier(self) -> None:
        """Routes capable of entering the top-four future-option value.

        The frontier is the union of the highest rule-score upper bounds and
        the highest current posterior values. A one-card successor cannot
        make a low-score, low-current-value route dominate both groups, so
        excluding the remainder is a branch-and-bound optimization rather
        than a route plan.
        """
        available = [
            route for route in self._contracted(self._view.claimed_by).routes
            if route.length <= self._view.trains_remaining
        ]
        by_upper_bound = sorted(
            available,
            key=lambda route: (
                Game.SCORE_TABLE.get(route.length, route.length), route.length
            ),
            reverse=True,
        )[:12]
        by_current_value = sorted(
            available,
            key=lambda route: (
                (Game.SCORE_TABLE.get(route.length, route.length) + 0.12 * route.length)
                / max(self._route_acquisition_turns(route, self._view.hand), 1.0) ** 0.78
            ),
            reverse=True,
        )[:16]
        self._option_route_ids = {
            route.route_id for route in (*by_upper_bound, *by_current_value)
        }

    def _network_value(self, claimed_by) -> float:
        parent = {}

        def find(city):
            parent.setdefault(city, city)
            if parent[city] != city:
                parent[city] = find(parent[city])
            return parent[city]

        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parent[a] = b

        owned = [
            route for route in self._view.routes
            if claimed_by.get(route.route_id) == self._view.player_id
        ]
        for route in owned:
            union(route.city1, route.city2)
        # Each city appears once per incident edge above; recompute unique
        # members so hubs do not receive artificial extra value.
        members = {}
        for route in owned:
            for city in (route.city1, route.city2):
                members.setdefault(find(city), set()).add(city)
        return self._NETWORK_PAIR_VALUE * sum(
            len(cities) * (len(cities) - 1) / 2 for cities in members.values()
        )

    def _longest_path_equity(self, claimed_by) -> float:
        base_ids = {
            route_id for route_id, owner in self._view.claimed_by.items()
            if owner == self._view.player_id
        }
        added_length = sum(
            self._routes_by_id[route_id].length
            for route_id, owner in claimed_by.items()
            if owner == self._view.player_id and route_id not in base_ids
        )
        current = self._view.longest_paths.get(self._view.player_id, 0)
        estimate = current + 0.72 * added_length
        opposing_best = max(
            (self._view.longest_paths.get(opponent.player_id, 0)
             for opponent in self._view.opponents),
            default=0,
        )
        probability = self._sigmoid((estimate - opposing_best) / 2.4)
        current_bonus = 10.0 if self._view.longest_path_holder == self._view.player_id else 0.0
        return 10.0 * probability - current_bonus

    # ------------------------------------------------------------------
    # Ticket posterior value
    # ------------------------------------------------------------------

    def _ticket_set_utility(self, tickets, hand, claimed_by, trains_remaining: int) -> float:
        projections = []
        route_ids = set()
        pending = [
            ticket for ticket in tickets
            if not ticket.is_completed and not ticket.is_impossible
        ]
        portfolio_paths = self._portfolio_paths(pending, claimed_by)
        for ticket in pending:
            probability, path, trains_needed, expected_turns = self._ticket_projection(
                ticket,
                hand,
                claimed_by,
                trains_remaining,
                path_override=portfolio_paths.get(self._ticket_signature(ticket)),
            )
            projections.append(
                (ticket, probability, path, trains_needed, expected_turns)
            )
            route_ids.update(path)

        committed_trains = sum(self._routes_by_id[route_id].length for route_id in route_ids)
        portfolio_turns = sum(
            self._route_acquisition_turns(self._routes_by_id[route_id], hand)
            for route_id in route_ids
        )
        trigger = min(
            [trains_remaining, *(opponent.remaining_trains for opponent in self._view.opponents)]
        )
        rounds_left = 1.0 if trigger <= 2 else 1.0 + (trigger - 2) / 2.7
        time_capacity = self._sigmoid((rounds_left - portfolio_turns) / 2.1)
        train_capacity = self._sigmoid(
            (trains_remaining - committed_trains + 0.5) / 1.6
        )
        portfolio_capacity = min(time_capacity, train_capacity)

        total = 0.0
        for ticket, probability, path, trains_needed, expected_turns in projections:
            # All uncompleted tickets compete for the same turns, cards, and
            # trains. Cap each independent path probability by the joint
            # portfolio's feasibility; already-connected tickets need no
            # remaining portfolio resources and retain certainty.
            joint_probability = probability if not path else min(
                probability, portfolio_capacity
            )
            expected_payoff = (2.0 * joint_probability - 1.0) * ticket.value
            if expected_payoff > 0.0:
                expected_payoff /= 1.0 + self._TICKET_TIME_DISCOUNT * expected_turns
            total += expected_payoff - self._TRAIN_SHADOW_PRICE * trains_needed
        return total

    @staticmethod
    def _ticket_signature(ticket) -> tuple:
        return (ticket.city1, ticket.city2, ticket.value)

    def _ticket_projection(
        self, ticket, hand, claimed_by, trains_remaining: int, path_override=None
    ):
        path_key = None if path_override is None else tuple(
            route.route_id for route in path_override
        )
        key = (
            ticket.city1,
            ticket.city2,
            self._hand_key(hand),
            self._claim_key(claimed_by),
            trains_remaining,
            path_key,
        )
        cached = self._projection_cache.get(key)
        if cached is not None:
            return cached

        path = (
            self._ticket_path(ticket, claimed_by)
            if path_override is None else path_override
        )
        if path is None:
            result = (0.0, (), trains_remaining + 1, float("inf"))
            self._projection_cache[key] = result
            return result
        if not path:
            result = (1.0, (), 0, 0.0)
            self._projection_cache[key] = result
            return result

        trains_needed = sum(route.length for route in path)
        expected_turns = sum(self._route_acquisition_turns(route, hand) for route in path)
        survival = math.prod(1.0 - self._block_probability(route) for route in path)
        trigger = min(
            [trains_remaining, *(opponent.remaining_trains for opponent in self._view.opponents)]
        )
        rounds_left = 1.0 if trigger <= 2 else 1.0 + (trigger - 2) / 2.7
        time_probability = self._sigmoid((rounds_left - expected_turns) / 2.1)
        budget_probability = self._sigmoid((trains_remaining - trains_needed + 0.5) / 1.6)
        # Hazard in path cost prices likely rerouting; survival retains the
        # correlated failure risk of portfolios sharing chokepoints.
        probability = max(0.0, min(
            1.0,
            survival * time_probability * budget_probability,
        ))
        result = (
            probability,
            tuple(route.route_id for route in path),
            trains_needed,
            expected_turns,
        )
        self._projection_cache[key] = result
        return result

    def _ticket_path(self, ticket, claimed_by):
        """Risk-adjusted structural path, cached once per board state.

        Card successors reprice the same topology instead of rerunning graph
        search. The structural edge prior uses claim turns, train length, and
        posterior block hazard; hand-specific affordability is applied later
        by ``_ticket_projection``.
        """
        key = (ticket.city1, ticket.city2, self._claim_key(claimed_by))
        if key in self._ticket_path_cache:
            return self._ticket_path_cache[key]

        result = self._search_ticket_path(ticket, claimed_by, frozenset())
        self._ticket_path_cache[key] = result
        return result

    def _search_ticket_path(self, ticket, claimed_by, free_route_ids):
        culled = self._contracted(claimed_by)
        if ticket.city1 not in culled.city_to_node or ticket.city2 not in culled.city_to_node:
            return None
        start = culled.city_to_node[ticket.city1]
        goal = culled.city_to_node[ticket.city2]
        if start == goal:
            return ()

        best = {start: 0.0}
        predecessor = {}
        frontier = [(0.0, start)]
        while frontier:
            cost, node = heapq.heappop(frontier)
            if cost > best.get(node, cost):
                continue
            if node == goal:
                break
            for neighbor, route in culled.adjacency().get(node, []):
                block = self._block_probability(route)
                hazard = -math.log(max(1e-6, 1.0 - block))
                structural_turns = 1.0 + route.length / self._DRAW_PICKS_PER_TURN
                edge_cost = (
                    0.05 if route.route_id in free_route_ids
                    else structural_turns + self._BLOCK_HAZARD_WEIGHT * hazard
                )
                candidate = cost + edge_cost
                if candidate < best.get(neighbor, float("inf")):
                    best[neighbor] = candidate
                    predecessor[neighbor] = (node, route)
                    heapq.heappush(frontier, (candidate, neighbor))

        if goal not in best:
            return None

        path = []
        node = goal
        while node != start:
            node, route = predecessor[node]
            path.append(route)
        return tuple(path)

    def _portfolio_paths(self, tickets, claimed_by):
        signatures = tuple(sorted(self._ticket_signature(ticket) for ticket in tickets))
        key = (signatures, self._claim_key(claimed_by))
        cached = self._portfolio_path_cache.get(key)
        if cached is not None:
            return cached
        paths = {
            self._ticket_signature(ticket): self._ticket_path(ticket, claimed_by)
            for ticket in tickets
        }
        for _ in range(2):
            for ticket in tickets:
                signature = self._ticket_signature(ticket)
                free_routes = {
                    route.route_id
                    for other_signature, path in paths.items()
                    if other_signature != signature and path is not None
                    for route in path
                }
                paths[signature] = self._search_ticket_path(
                    ticket, claimed_by, frozenset(free_routes)
                )
        self._portfolio_path_cache[key] = paths
        return paths

    def _keep_utility(self, action: KeepTickets) -> float:
        offered = self._view.ticket_offer or []
        chosen = [offered[index] for index in action.indices]
        return self._ticket_set_utility(
            [*self._view.tickets, *chosen],
            self._view.hand,
            self._view.claimed_by,
            self._view.trains_remaining,
        )

    def _load_ticket_prior(self) -> None:
        if self._ticket_prior_map == self._view.map_name:
            return
        self._ticket_prior_map = self._view.map_name
        self._ticket_prior = []
        cities = {city for route in self._view.routes for city in (route.city1, route.city2)}
        try:
            with resolve_tickets_path(self._view.map_name).open(
                newline="", encoding="utf-8"
            ) as handle:
                for row in csv.DictReader(handle):
                    if row["city1"] in cities and row["city2"] in cities:
                        self._ticket_prior.append(DestinationTicket(
                            row["city1"], row["city2"], int(row["value"])
                        ))
        except (OSError, KeyError, ValueError):
            self._ticket_prior = []

    def _ticket_offer_expected_utility(self) -> float:
        known = Counter((ticket.city1, ticket.city2, ticket.value) for ticket in self._view.tickets)
        candidates = []
        current_value = self._ticket_set_utility(
            self._view.tickets,
            self._view.hand,
            self._view.claimed_by,
            self._view.trains_remaining,
        )
        for ticket in self._ticket_prior:
            signature = (ticket.city1, ticket.city2, ticket.value)
            if known[signature]:
                known[signature] -= 1
                continue
            candidate_value = self._ticket_set_utility(
                [*self._view.tickets, ticket],
                self._view.hand,
                self._view.claimed_by,
                self._view.trains_remaining,
            )
            candidates.append(candidate_value - current_value)
        if not candidates:
            return -1e9
        if len(candidates) < 3:
            return max(candidates)

        total = 0.0
        count = 0
        for offer in combinations(candidates, 3):
            positive = [value for value in offer if value > 0.0]
            total += sum(positive) if positive else max(offer)
            count += 1
        # Drawing tickets consumes the action without improving the train
        # hand, so compare the offer to the best currently available route
        # option rather than treating information as free.
        opportunity = 0.35 * self._route_option_value(
            self._view.hand, self._view.claimed_by, self._view.trains_remaining
        )
        opposing_score = max(
            (opponent.score for opponent in self._view.opponents), default=self._view.score
        )
        # Ticket offers have much higher outcome variance than cards or a
        # deterministic claim. Under a win-probability objective, variance
        # is valuable while trailing and costly while protecting a lead.
        risk_premium = max(
            -1.5, min(1.5, (opposing_score - self._view.score) / 25.0)
        )
        return total / count - opportunity + risk_premium

    # ------------------------------------------------------------------
    # Card acquisition and Bayesian opponent model
    # ------------------------------------------------------------------

    def _payment_demands(self, route: Route):
        cached = self._payment_cache.get(route.route_id)
        if cached is not None:
            return cached

        locomotive_components = 0
        states = {tuple(0 for _ in self._COLORS)}
        for component in route.cost:
            if component.is_locomotive():
                locomotive_components += component.count
                continue
            next_states = set()
            for state in states:
                for color in component.concrete_options():
                    counts = list(state)
                    counts[self._COLORS.index(color)] += component.count
                    next_states.add(tuple(counts))
            if len(next_states) > self._MAX_PAYMENT_STATES:
                next_states = set(sorted(
                    next_states,
                    key=lambda demand: (max(demand), demand),
                )[:self._MAX_PAYMENT_STATES])
            states = next_states
        locomotive_floor = max(route.locomotives, locomotive_components)
        result = [(demand, locomotive_floor) for demand in sorted(states)]
        self._payment_cache[route.route_id] = result
        return result

    def _route_acquisition_turns(self, route: Route, hand) -> float:
        key = (route.route_id, self._hand_key(hand))
        cached = self._turn_cost_cache.get(key)
        if cached is not None:
            return cached
        turns = min(
            (self._payment_expected_turns(demand, floor, hand)
             for demand, floor in self._payment_demands(route)),
            default=float("inf"),
        )
        self._turn_cost_cache[key] = turns
        return turns

    def _payment_expected_turns(self, demand, locomotive_floor: int, hand) -> float:
        held_locomotives = hand.get("L", 0)
        mandatory_locomotives = max(0, locomotive_floor - held_locomotives)
        spare_locomotives = max(0, held_locomotives - locomotive_floor)
        deficits = [
            max(0, demand[index] - hand.get(color, 0))
            for index, color in enumerate(self._COLORS)
        ]
        while spare_locomotives and any(deficits):
            target = max(
                range(len(deficits)),
                key=lambda index: deficits[index] / max(
                    self._odds.get(self._COLORS[index], 0.0) + self._odds.get("L", 0.0),
                    1e-9,
                ),
            )
            deficits[target] -= 1
            spare_locomotives -= 1
        if not mandatory_locomotives and not any(deficits):
            return 1.0

        locomotive_odds = self._odds.get("L", 0.0)
        if mandatory_locomotives and locomotive_odds <= 0.0:
            return float("inf")
        active = [index for index, deficit in enumerate(deficits) if deficit]
        useful_odds = sum(self._odds.get(self._COLORS[index], 0.0) for index in active)
        if active:
            useful_odds += locomotive_odds
        if active and useful_odds <= 0.0:
            return float("inf")

        total_bound = sum(deficits) / useful_odds if active else 0.0
        quota_bound = max((
            deficits[index] / (
                self._odds.get(self._COLORS[index], 0.0) + locomotive_odds
            )
            for index in active
        ), default=0.0)
        mandatory_bound = (
            mandatory_locomotives / locomotive_odds if mandatory_locomotives else 0.0
        )
        expected_picks = mandatory_bound + max(total_bound, quota_bound)
        return 1.0 + expected_picks / self._DRAW_PICKS_PER_TURN

    @staticmethod
    def _hypergeom_tail(population: int, successes: int, draws: int, needed: int) -> float:
        if needed <= 0:
            return 1.0
        draws = min(max(0, draws), population)
        successes = min(max(0, successes), population)
        if needed > min(draws, successes) or population <= 0:
            return 0.0
        denominator = math.comb(population, draws)
        lower = max(needed, draws - (population - successes))
        upper = min(draws, successes)
        return sum(
            math.comb(successes, hits)
            * math.comb(population - successes, draws - hits)
            for hits in range(lower, upper + 1)
        ) / denominator

    def _opponent_affordability(self, route: Route, opponent) -> float:
        population = self._unknown.total()
        hidden = max(0, opponent.num_cards_in_hand - opponent.exposed_hand.total())
        best = 0.0
        for demand, floor in self._payment_demands(route):
            exposed_locomotives = opponent.exposed_hand.get("L", 0)
            locomotive_need = max(0, floor - exposed_locomotives)
            spare_exposed_locomotives = max(0, exposed_locomotives - floor)
            deficits = [
                max(0, demand[index] - opponent.exposed_hand.get(color, 0))
                for index, color in enumerate(self._COLORS)
            ]
            while spare_exposed_locomotives and any(deficits):
                index = max(range(len(deficits)), key=deficits.__getitem__)
                deficits[index] -= 1
                spare_exposed_locomotives -= 1

            constraints = []
            if locomotive_need:
                constraints.append(self._hypergeom_tail(
                    population, self._unknown.get("L", 0), hidden, locomotive_need
                ))
            for index, deficit in enumerate(deficits):
                if not deficit:
                    continue
                useful = self._unknown.get(self._COLORS[index], 0) + self._unknown.get("L", 0)
                constraints.append(self._hypergeom_tail(
                    population, useful, hidden, deficit
                ))
            if not constraints:
                probability = 1.0
            else:
                probability = min(constraints) * math.prod(constraints) ** 0.25
            best = max(best, min(1.0, probability))
        return best

    def _opponent_route_intent(self, route: Route, opponent) -> float:
        components = self._opponent_components[opponent.player_id]
        first = next((index for index, cities in enumerate(components) if route.city1 in cities), None)
        second = next((index for index, cities in enumerate(components) if route.city2 in cities), None)
        if first is not None and first == second:
            likelihood_ratio = 0.15
        elif first is not None and second is not None:
            likelihood_ratio = 7.0
        elif first is not None or second is not None:
            likelihood_ratio = 3.2
        else:
            likelihood_ratio = 1.0
        points = Game.SCORE_TABLE.get(route.length, route.length)
        prior = min(0.28, 0.055 + 0.012 * points)
        prior_odds = prior / (1.0 - prior)
        posterior_odds = prior_odds * likelihood_ratio
        return posterior_odds / (1.0 + posterior_odds)

    def _block_probability(self, route: Route) -> float:
        cached = self._block_cache.get(route.route_id)
        if cached is not None:
            return cached
        survival = 1.0
        for opponent in self._view.opponents:
            probability = (
                self._opponent_affordability(route, opponent)
                * self._opponent_route_intent(route, opponent)
            )
            survival *= 1.0 - min(0.95, probability)
        result = 1.0 - survival
        self._block_cache[route.route_id] = result
        return result


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from notebook_harness.spectate import spectate_controls

    map_picker, seat_pickers, rounds_picker = spectate_controls(
        mo,
        bot_name=BOT_META["name"],
        bot_class=BayesianUtilityBot,
        title=BOT_META["name"],
    )
    return map_picker, mo, rounds_picker, seat_pickers


@app.cell(hide_code=True)
def _(map_picker, mo, rounds_picker, seat_pickers):
    from notebook_harness.spectate import play_match

    harness_series = play_match(mo, map_picker, seat_pickers, rounds_picker)
    return (harness_series,)


@app.cell(hide_code=True)
def _(harness_series, mo):
    from notebook_harness.spectate import spectate_widgets

    shell = spectate_widgets(mo, harness_series)
    return (shell,)


@app.cell(hide_code=True)
def _(harness_series, mo, shell):
    from notebook_harness.spectate import spectate_view

    spectate_view(mo, harness_series, shell)
    return


if __name__ == "__main__":
    app.run()
