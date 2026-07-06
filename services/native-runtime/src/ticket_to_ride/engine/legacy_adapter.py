"""Adapter that drives a choose_*-style bot through the act() interface.

Player wraps any interface without a callable act() in this adapter, so
every pre-action-model bot (notebook bots, the runtime's bootstrap bot,
sandboxed API clients) keeps working unchanged.
"""
import logging

from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets,
)

logger = logging.getLogger(__name__)


class LegacyBotAdapter:
    def __init__(self, bot):
        self.bot = bot

    def set_player(self, player):
        self.player = player
        self.bot.set_player(player)

    def begin_turn(self):
        hook = getattr(self.bot, "begin_turn", None)
        if callable(hook):
            hook()

    def end_turn(self, completed):
        hook = getattr(self.bot, "end_turn", None)
        if callable(hook):
            hook(completed)

    def act(self, view, legal_actions):
        if view.decision == "keep_tickets":
            return self._keep(view, legal_actions)
        if view.decision == "draw_second":
            return self._draw(self.bot.choose_draw_train_action(), legal_actions)
        return self._turn(view, legal_actions)

    def _turn(self, view, legal_actions):
        claims = [a for a in legal_actions if isinstance(a, ClaimRoute)]
        draws = [a for a in legal_actions if isinstance(a, (DrawBlind, DrawFaceUp))]
        tickets_offered = any(isinstance(a, DrawTickets) for a in legal_actions)
        choice = self.bot.choose_turn_action()
        if choice == 3 and tickets_offered:
            return DrawTickets()
        if choice == 2 and claims:
            return self._claim(view, claims)
        if draws:
            return self._draw(self.bot.choose_draw_train_action(), draws)
        if claims:  # deck dry: forced claim, like the old draw_train fault flag
            return self._claim(view, claims)
        if tickets_offered:
            return DrawTickets()
        return legal_actions[0]

    def _draw(self, pick, legal_actions):
        if pick >= 0:
            for action in legal_actions:
                if isinstance(action, DrawFaceUp) and action.index == pick:
                    return action
        for action in legal_actions:
            if isinstance(action, DrawBlind):
                return action
        return legal_actions[0]

    def _claim(self, view, claims):
        # Rebuild the (route, locomotives) menu the legacy contract expects:
        # one entry per route, at its minimum locomotive spend.
        options = {}
        for action in claims:
            current = options.get(action.route_id)
            if current is None or action.locomotives < current[1]:
                options[action.route_id] = (view.route_by_id(action.route_id), action.locomotives)
        route, locomotives = self.bot.choose_route_to_claim(list(options.values()))
        candidates = [a for a in claims if a.route_id == route.route_id and a.locomotives == locomotives]
        if not candidates:
            candidates = [a for a in claims if a.route_id == route.route_id] or claims
        if len(candidates) > 1:
            colors = [a.color for a in candidates if a.color != "L"]
            chosen_color = self.bot.choose_color_to_spend(route, colors)
            for action in candidates:
                if action.color == chosen_color:
                    return action
            # legacy None/invalid answer: spend the largest stack, mirroring
            # the old engine fallback
            hand = view.hand
            return max(candidates, key=lambda a: hand.get(a.color, 0))
        return candidates[0]

    def _keep(self, view, legal_actions):
        offer = view.ticket_offer
        kept = self.bot.select_ticket_offer(offer)
        indices = tuple(sorted(offer.index(t) for t in kept if t in offer))
        choice = KeepTickets(indices)
        if choice in legal_actions:
            return choice
        supersets = [
            a for a in legal_actions
            if isinstance(a, KeepTickets) and set(indices) <= set(a.indices)
        ]
        if supersets:
            return min(supersets, key=lambda a: len(a.indices))
        logger.warning("Legacy keep %r has no legal mapping; using %r", indices, legal_actions[0])
        return legal_actions[0]
