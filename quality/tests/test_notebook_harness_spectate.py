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


class FakeNumber:
    def __init__(self, *, start, stop, value, label) -> None:
        self.start = start
        self.stop = stop
        self.value = value
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
    def __init__(self) -> None:
        self.anywidget_calls = []

    def dropdown(self, *, options, value, label):
        return FakeDropdown(options=options, value=value, label=label)

    def number(self, *, start, stop, value, label):
        return FakeNumber(start=start, stop=stop, value=value, label=label)

    def array(self, items):
        return FakeArray(items)

    def anywidget(self, widget):
        self.anywidget_calls.append(widget)
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


class SpectateControlsTests(unittest.TestCase):
    def test_spectate_controls_returns_map_seat_and_rounds_picker_globals(self) -> None:
        mo = FakeMo()
        live_bot = type("LiveBot", (), {})
        discovered_bot = type("DiscoveredBot", (), {})

        with patch("notebook_harness.game_runner.list_maps", return_value=["classic", "mini"]), \
             patch("notebook_harness.game_runner.available_bots", return_value={"Other Bot": discovered_bot}):
            map_picker, seat_pickers, rounds_picker = spectate.spectate_controls(
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
        self.assertEqual(rounds_picker.value, 1)
        self.assertEqual(rounds_picker.start, 1)
        self.assertEqual(rounds_picker.stop, 20)
        self.assertEqual(rounds_picker.label, "Rounds")

    def test_spectate_controls_appends_title_and_picker_layout(self) -> None:
        mo = FakeMo()

        with patch("notebook_harness.game_runner.list_maps", return_value=["classic"]), \
             patch("notebook_harness.game_runner.available_bots", return_value={}):
            spectate.spectate_controls(mo, bot_name="Live Bot", bot_class=object, title="Live Bot")

        self.assertEqual([element.kind for element in mo.output.appended], ["md", "hstack"])
        self.assertEqual(mo.output.appended[0].text, "# Live Bot - spectate & debug")
        layout = mo.output.appended[1]
        self.assertEqual(layout.children[0].label, "Map")
        self.assertEqual(layout.children[1].label, "Rounds")


class PlayMatchTests(unittest.TestCase):
    def test_play_match_stops_when_fewer_than_two_seats_are_selected(self) -> None:
        mo = FakeMo()
        map_picker = SimpleNamespace(value="classic")
        seat_pickers = SimpleNamespace(value=[object(), None, None, None, None])
        rounds_picker = SimpleNamespace(value=1)

        with self.assertRaisesRegex(FakeStop, "Pick bots for at least two seats"):
            spectate.play_match(mo, map_picker, seat_pickers, rounds_picker)

    def test_play_match_initializes_and_plays_the_selected_rounds(self) -> None:
        mo = FakeMo()
        bot_a = Mock(return_value="bot-a")
        bot_b = Mock(return_value="bot-b")
        series = Mock()
        series.round_count.return_value = 2
        map_picker = SimpleNamespace(value="classic")
        seat_pickers = SimpleNamespace(value=[bot_a, None, bot_b, None, None])
        rounds_picker = SimpleNamespace(value=2)

        with patch("notebook_harness.game_runner.initialize_series", return_value=series) as initialize_series:
            result = spectate.play_match(mo, map_picker, seat_pickers, rounds_picker)

        self.assertIs(result, series)
        initialize_series.assert_called_once_with([bot_a, bot_b], map_name="classic", rounds=2)
        series.play.assert_called_once_with()
        self.assertEqual(result.round_count(), 2)

    def test_play_match_defaults_to_one_round_without_a_rounds_picker(self) -> None:
        mo = FakeMo()
        bot_a = Mock(return_value="bot-a")
        bot_b = Mock(return_value="bot-b")
        series = Mock()
        series.round_count.return_value = 1
        map_picker = SimpleNamespace(value="classic")
        seat_pickers = SimpleNamespace(value=[bot_a, bot_b, None, None, None])

        with patch("notebook_harness.game_runner.initialize_series", return_value=series) as initialize_series:
            spectate.play_match(mo, map_picker, seat_pickers)

        initialize_series.assert_called_once_with([bot_a, bot_b], map_name="classic", rounds=1)


class SpectateWidgetsTests(unittest.TestCase):
    def test_spectate_widgets_builds_a_single_shell_widget(self) -> None:
        mo = FakeMo()
        series = Mock()
        built_shell = object()

        with patch("notebook_harness.spectate_shell_widget.build_shell", return_value=built_shell) as build_shell:
            shell = spectate.spectate_widgets(mo, series)

        build_shell.assert_called_once_with(series)
        self.assertIs(shell, built_shell)
        self.assertEqual(mo.ui.anywidget_calls, [built_shell])

    def test_spectate_widgets_does_not_render_output(self) -> None:
        # Creation and display live in different cells: the widgets cell must
        # not append anything, or the layout would show up twice.
        mo = FakeMo()

        with patch("notebook_harness.spectate_shell_widget.build_shell", return_value=object()):
            spectate.spectate_widgets(mo, Mock())

        self.assertEqual(mo.output.appended, [])


class SpectateViewTests(unittest.TestCase):
    def test_spectate_view_updates_the_shell_and_appends_it_once(self) -> None:
        mo = FakeMo()
        series = Mock()
        shell = object()

        with patch("notebook_harness.spectate_shell_widget.update_shell") as update_shell:
            spectate.spectate_view(mo, series, shell)

        update_shell.assert_called_once_with(shell, series)
        self.assertEqual(mo.output.appended, [shell])


if __name__ == "__main__":
    unittest.main()
