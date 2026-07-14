from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from notebook_harness import spectate


class FakeStop(Exception):
    pass


class FakeElement:
    def __init__(self, kind: str, children=None, text: str = "") -> None:
        self.kind = kind
        self.children = list(children or [])
        self.text = text

    def left(self):
        self.alignment = "left"
        return self


class FakeDropdown:
    def __init__(self, *, options, value, label) -> None:
        self.options = options
        self.value = options[value] if isinstance(options, dict) else value
        self.label = label


class FakeArray:
    def __init__(self, items) -> None:
        self.items = list(items)
        self.value = [item.value for item in self.items]


class FakeOutput:
    def __init__(self) -> None:
        self.appended = []

    def append(self, element) -> None:
        self.appended.append(element)


class FakeUI:
    def dropdown(self, *, options, value, label):
        return FakeDropdown(options=options, value=value, label=label)

    def array(self, items):
        return FakeArray(items)

    def anywidget(self, widget):
        return widget


class FakeMo:
    def __init__(self) -> None:
        self.ui = FakeUI()
        self.output = FakeOutput()
        self.stop_calls = []

    def md(self, text):
        return FakeElement("md", text=text)

    def hstack(self, children, **kwargs):
        element = FakeElement("hstack", children)
        element.kwargs = kwargs
        return element

    def vstack(self, children, **kwargs):
        element = FakeElement("vstack", children)
        element.kwargs = kwargs
        return element

    def stop(self, condition, output):
        self.stop_calls.append((condition, output))
        if condition:
            raise FakeStop(output.text)


class FakeGraph:
    def __init__(self, *, data) -> None:
        self.data = data


class FakePlayerList:
    def __init__(self, *, players) -> None:
        self.players = players
        self.value = {"selected_player": ""}


class FakeInfoBar:
    def __init__(self, *, market) -> None:
        self.market = market


class FakeSlider:
    def __init__(self, *, min_value, max_value, step, interval_ms) -> None:
        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.interval_ms = interval_ms
        self.value = {"value": min_value}


class FakeHarnessGame:
    def __init__(self) -> None:
        self.board_calls = []
        self.market_calls = []
        self.play = Mock()

    def snapshot_count(self):
        return 4

    def board_at(self, step, viewpoint=None):
        self.board_calls.append((step, viewpoint))
        return [{"id": f"node-{step}-{viewpoint}"}], [{"id": f"edge-{step}-{viewpoint}"}]

    def market_at(self, step, viewpoint=None):
        self.market_calls.append((step, viewpoint))
        return {"step": step, "viewpoint": viewpoint}

    def roster(self):
        return [{"id": "bot_0", "name": "Alpha", "color": "red"}]


FAKE_WIDGET_CLASSES = (
    FakeGraph,
    FakePlayerList,
    FakeInfoBar,
    lambda nodes, edges: {"nodes": nodes, "links": edges},
    FakeSlider,
)


class SpectateControlsTests(unittest.TestCase):
    def test_spectate_controls_returns_map_and_seat_picker_globals(self) -> None:
        mo = FakeMo()
        live_bot = type("LiveBot", (), {})
        discovered_bot = type("DiscoveredBot", (), {})

        with patch("notebook_harness.game_runner.list_maps", return_value=["classic", "mini"]), \
             patch("notebook_harness.game_runner.available_bots", return_value={"Other Bot": discovered_bot}):
            map_picker, seat_pickers = spectate.spectate_controls(
                mo,
                bot_name="Live Bot",
                bot_class=live_bot,
                title="Live Bot",
            )

        self.assertEqual(map_picker.value, "classic")
        self.assertEqual(map_picker.options, ["classic", "mini"])
        self.assertEqual(seat_pickers.value[:2], [live_bot, live_bot])
        self.assertEqual(seat_pickers.value[2:], [None, None, None])
        self.assertEqual(seat_pickers.items[0].options["Live Bot"], live_bot)
        self.assertEqual(seat_pickers.items[0].options["Other Bot"], discovered_bot)

    def test_spectate_controls_appends_title_and_picker_layout(self) -> None:
        mo = FakeMo()

        with patch("notebook_harness.game_runner.list_maps", return_value=["classic"]), \
             patch("notebook_harness.game_runner.available_bots", return_value={}):
            spectate.spectate_controls(mo, bot_name="Live Bot", bot_class=object, title="Live Bot")

        self.assertEqual([element.kind for element in mo.output.appended], ["md", "hstack"])
        self.assertEqual(mo.output.appended[0].text, "# Live Bot - spectate & debug")
        self.assertEqual(mo.output.appended[1].children[0].label, "Map")


class PlayMatchTests(unittest.TestCase):
    def test_play_match_stops_when_fewer_than_two_seats_are_selected(self) -> None:
        mo = FakeMo()
        map_picker = SimpleNamespace(value="classic")
        seat_pickers = SimpleNamespace(value=[object(), None, None, None, None])

        with self.assertRaisesRegex(FakeStop, "Pick bots for at least two seats"):
            spectate.play_match(mo, map_picker, seat_pickers)

    def test_play_match_initializes_and_plays_selected_bots(self) -> None:
        mo = FakeMo()
        bot_a = Mock(return_value="bot-a")
        bot_b = Mock(return_value="bot-b")
        game = FakeHarnessGame()
        map_picker = SimpleNamespace(value="classic")
        seat_pickers = SimpleNamespace(value=[bot_a, None, bot_b, None, None])

        with patch("notebook_harness.game_runner.initialize_game", return_value=game) as initialize_game:
            result = spectate.play_match(mo, map_picker, seat_pickers)

        self.assertIs(result, game)
        initialize_game.assert_called_once_with(["bot-a", "bot-b"], map_name="classic")
        game.play.assert_called_once_with()


class SpectateWidgetsTests(unittest.TestCase):
    def test_spectate_widgets_builds_the_four_view_widgets_from_step_zero(self) -> None:
        mo = FakeMo()
        game = FakeHarnessGame()

        with patch("notebook_harness.spectate._load_widget_classes", return_value=FAKE_WIDGET_CLASSES):
            graph, player_list, info_bar, step_slider = spectate.spectate_widgets(mo, game)

        self.assertIsInstance(graph, FakeGraph)
        self.assertIsInstance(player_list, FakePlayerList)
        self.assertIsInstance(info_bar, FakeInfoBar)
        self.assertIsInstance(step_slider, FakeSlider)
        self.assertEqual(graph.data["nodes"], [{"id": "node-0-None"}])
        self.assertEqual(player_list.players, game.roster())
        self.assertEqual(info_bar.market, {"step": 0, "viewpoint": None})
        self.assertEqual(step_slider.max_value, 3)

    def test_spectate_widgets_does_not_render_output(self) -> None:
        # Creation and display live in different cells: the widgets cell must
        # not append anything, or the layout would show up twice.
        mo = FakeMo()

        with patch("notebook_harness.spectate._load_widget_classes", return_value=FAKE_WIDGET_CLASSES):
            spectate.spectate_widgets(mo, FakeHarnessGame())

        self.assertEqual(mo.output.appended, [])


class SpectateViewTests(unittest.TestCase):
    def _widgets(self, mo, game):
        with patch("notebook_harness.spectate._load_widget_classes", return_value=FAKE_WIDGET_CLASSES):
            return spectate.spectate_widgets(mo, game)

    def _view(self, mo, game, widgets):
        with patch("notebook_harness.spectate._load_widget_classes", return_value=FAKE_WIDGET_CLASSES):
            spectate.spectate_view(mo, game, *widgets)

    def test_spectate_view_updates_widgets_for_the_current_step_and_viewpoint(self) -> None:
        mo = FakeMo()
        game = FakeHarnessGame()
        graph, player_list, info_bar, step_slider = widgets = self._widgets(mo, game)
        player_list.value = {"selected_player": "bot_0"}
        step_slider.value = {"value": 2}

        self._view(mo, game, widgets)

        self.assertEqual(game.board_calls[-1], (2, "bot_0"))
        self.assertEqual(game.market_calls[-1], (2, "bot_0"))
        self.assertEqual(graph.data["nodes"], [{"id": "node-2-bot_0"}])
        self.assertEqual(info_bar.market, {"step": 2, "viewpoint": "bot_0"})

    def test_spectate_view_defaults_to_step_zero_spectator(self) -> None:
        mo = FakeMo()
        game = FakeHarnessGame()
        widgets = self._widgets(mo, game)

        self._view(mo, game, widgets)

        self.assertEqual(game.board_calls[-1], (0, None))
        self.assertEqual(game.market_calls[-1], (0, None))

    def test_spectate_view_appends_the_layout(self) -> None:
        mo = FakeMo()
        game = FakeHarnessGame()
        graph, player_list, info_bar, step_slider = widgets = self._widgets(mo, game)

        self._view(mo, game, widgets)

        layout = mo.output.appended[-1]
        self.assertEqual(layout.kind, "vstack")
        self.assertIs(layout.children[0], step_slider)
        self.assertEqual(layout.children[1].kind, "hstack")
        self.assertIs(layout.children[1].children[0], graph)
        self.assertIs(layout.children[1].children[1], player_list)
        self.assertIs(layout.children[2], info_bar)


if __name__ == "__main__":
    unittest.main()
