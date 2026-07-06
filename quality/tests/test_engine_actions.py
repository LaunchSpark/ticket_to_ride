import unittest

from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets, Pass,
    legal_claim_actions, legal_keep_actions, legal_second_draw_actions, legal_turn_actions,
)
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _game_and_player():
    context = GameContext(["p0", "p1"], seed=11)
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(2)]
    for p in players:
        p.attach(context, players)
    return context, players[0]


class LegalMenuTests(unittest.TestCase):
    def test_turn_menu_has_draws_and_tickets(self):
        context, player = _game_and_player()
        legal = legal_turn_actions(player)
        self.assertIn(DrawBlind(), legal)
        self.assertIn(DrawTickets(), legal)
        face_ups = [a for a in legal if isinstance(a, DrawFaceUp)]
        self.assertEqual(len(face_ups), 5)
        for action in face_ups:
            self.assertEqual(context.get_train_deck().get_face_up()[action.index], action.card)

    def test_no_cards_means_no_claims(self):
        _, player = _game_and_player()
        self.assertEqual(legal_claim_actions(player), [])

    def test_claims_enumerate_colors_and_locomotives(self):
        _, player = _game_and_player()
        player.get_hand().update(["R"] * 4 + ["L"] * 1)
        claims = legal_claim_actions(player)
        self.assertTrue(claims)
        for action in claims:
            self.assertIsInstance(action, ClaimRoute)
            self.assertIn(action.color, {"R", "L"})
        # both locomotive spends are enumerated for routes the hand affords
        self.assertEqual({a.locomotives for a in claims}, {0, 1})
        # a route claimable with 0 locomotives is also claimable with 1
        zero_loco = {a.route_id for a in claims if a.locomotives == 0}
        one_loco = {a.route_id for a in claims if a.locomotives == 1}
        self.assertTrue(zero_loco <= one_loco)

    def test_second_draw_excludes_locomotives(self):
        context, player = _game_and_player()
        legal = legal_second_draw_actions(player)
        for action in legal:
            if isinstance(action, DrawFaceUp):
                self.assertNotEqual(action.card, "L")

    def test_keep_menu_sizes(self):
        self.assertEqual(len(legal_keep_actions(3, 1)), 7)   # all non-empty subsets
        self.assertEqual(len(legal_keep_actions(3, 2)), 4)   # size >= 2
        self.assertEqual(len(legal_keep_actions(1, 2)), 1)   # floor clamps to offer size

    def test_route_by_id(self):
        context, _ = _game_and_player()
        route = context.get_map().routes[0]
        self.assertIs(context.get_map().route_by_id(route.route_id), route)

    def test_empty_menu_is_pass(self):
        context, player = _game_and_player()
        deck = context.get_train_deck()
        while len(deck):
            deck.draw_face_down()
        ticket_deck = context.get_ticket_deck()
        while len(ticket_deck) >= 3:
            ticket_deck.deal_unique(3)
        legal = legal_turn_actions(player)
        self.assertEqual(legal, [Pass()])


class _FirstLegalBot:
    """Claims when possible, otherwise takes the first legal action."""
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        for action in legal_actions:
            if isinstance(action, ClaimRoute):
                return action
        return legal_actions[0]


class _IllegalBot:
    def set_player(self, player):
        self.player = player
    def act(self, view, legal_actions):
        return "nonsense"


class _NullLogger:
    def record_turn(self, *args, **kwargs):
        return None


class ActTurnFlowTests(unittest.TestCase):
    def _run(self, bot_classes, seed=21):
        from ticket_to_ride.engine.game import Game
        players = [Player(f"p{i}", cls(), f"p{i}", "red") for i, cls in enumerate(bot_classes)]
        context = GameContext([p.player_id for p in players], seed=seed)
        game = Game(context, players, _NullLogger(), 0)
        game.play()
        return game

    def test_full_game_with_act_bots(self):
        game = self._run([_FirstLegalBot, _FirstLegalBot])
        self.assertTrue(any(p.trains_remaining <= 2 for p in game.players))
        deck = game.context.get_train_deck()
        total = (
            len(deck) + len(deck.get_discard_pile()) + len(deck.get_face_up())
            + sum(p.get_card_count() for p in game.players)
        )
        self.assertEqual(total, 110)

    def test_illegal_action_falls_back_and_completes(self):
        game = self._run([_IllegalBot, _FirstLegalBot])
        self.assertGreater(game.turn_index, 0)

    def test_setup_keeps_at_least_two_tickets(self):
        game = self._run([_FirstLegalBot, _FirstLegalBot])
        for p in game.players:
            self.assertGreaterEqual(len(p.get_tickets()), 2)


if __name__ == "__main__":
    unittest.main()
