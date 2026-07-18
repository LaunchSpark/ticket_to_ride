"""The shared spectate/debug UI every bot notebook renders.

Each bot notebook calls these four functions from four consecutive cells
(see integrations/external/bots/random_bot.py). All layout, widgets, and
update logic live here so a UI change lands in every notebook at once.

Marimo wiring notes, load-bearing:
- Marimo never re-runs a UI element's defining cell on interaction, so a
  widget's value can only be read reactively from a *different* cell than
  the one that bound it to a global. That forces the four-cell pipeline:
  controls -> game -> widgets -> view.
- ``spectate_widgets`` creates the single composite shell widget once per
  series (its cell only re-runs when ``harness_series`` changes);
  ``spectate_view`` pushes fresh payloads into that same instance on every
  playback/selection change, so the shell's force-sim node positions and
  interaction state persist across steps and only diffs animate.
- ``mo`` is passed in explicitly (each cell does ``import marimo as mo``):
  the file-header ``import marimo`` is not visible inside the kernel's cell
  namespace, and the explicit parameter lets the headless tests drive the
  wiring with a fake marimo object.
"""

from __future__ import annotations

from typing import Any


def spectate_controls(mo: Any, *, bot_name: str, bot_class: type, title: str | None = None):
    """Create and display the map, rounds, and seat picker controls for a
    bot notebook.

    ``bot_class`` is the notebook's live class, injected over the on-disk
    version the loader discovered so edits take effect without reloading.
    Returns (map_picker, seat_pickers, rounds_picker) for the cell to bind
    as globals.
    """

    from notebook_harness.game_runner import available_bots, list_maps

    maps = list_maps()
    bot_options = {"(empty)": None, **available_bots()}
    bot_options[bot_name] = bot_class

    if title:
        mo.output.append(mo.md(f"# {title} - spectate & debug").left())

    map_picker = mo.ui.dropdown(options=maps, value=maps[0], label="Map")
    rounds_picker = mo.ui.number(start=1, step=1, value=1, label="Rounds")
    seat_pickers = mo.ui.array(
        [
            mo.ui.dropdown(
                options=bot_options,
                value=bot_name if index < 2 else "(empty)",
                label=f"Seat {index + 1}",
            )
            for index in range(5)
        ]
    )
    mo.output.append(mo.hstack([map_picker, rounds_picker, seat_pickers], align="start", justify="start"))
    return map_picker, seat_pickers, rounds_picker


def play_match(mo: Any, map_picker: Any, seat_pickers: Any, rounds_picker: Any = None):
    """Run the selected bot seats on the selected map for the selected
    number of rounds."""

    from notebook_harness.game_runner import initialize_series
    from wigglystuff import ProgressBar

    seated_bot_classes = [bot_class for bot_class in seat_pickers.value if bot_class is not None]
    mo.stop(len(seated_bot_classes) < 2, mo.md("Pick bots for at least two seats to run a game."))

    rounds = int(rounds_picker.value) if rounds_picker is not None else 1
    progress = mo.ui.anywidget(ProgressBar(value=0, max_value=rounds))
    # Appending before the blocking play loop puts the live indicator at the
    # bottom of this match-setup cell and lets anywidget trait updates paint
    # between completed rounds.
    mo.output.append(progress)
    series = initialize_series(seated_bot_classes, map_name=map_picker.value, rounds=rounds)
    series.play(
        on_round_complete=lambda completed, total: setattr(
            progress, "value", completed
        )
    )
    return series


def spectate_widgets(mo: Any, harness_series: Any):
    """Create the shell once per series; playback/selection state lives in
    the widget, so force-sim node positions persist across steps."""
    from notebook_harness.spectate_shell_widget import build_shell

    return mo.ui.anywidget(build_shell(harness_series))


def spectate_view(mo: Any, harness_series: Any, shell: Any) -> None:
    """Push the shell's current playback/selection into fresh payloads and
    display it. Runs reactively whenever the shell's value changes."""
    from notebook_harness.spectate_shell_widget import update_shell

    update_shell(shell, harness_series)
    mo.output.append(shell)


def replay_controls(mo: Any, api_base: str | None = None):
    """Create a dropdown over the matches available from the replay API."""
    from notebook_harness.stored_match import DEFAULT_API_BASE, list_stored_matches

    base = api_base or DEFAULT_API_BASE
    matches = list_stored_matches(base)
    mo.stop(
        not matches,
        mo.md(f"No stored matches at {base}. Run `uv run run` and play one."),
    )
    options = {
        f"{record.get('name') or record['matchId']} ({record['matchId'][:8]})": record["matchId"]
        for record in matches
    }
    first = next(iter(options))
    match_picker = mo.ui.dropdown(options=options, value=first, label="Stored match")
    mo.output.append(match_picker)
    return match_picker


def load_replay(mo: Any, match_picker: Any, api_base: str | None = None):
    """Load the selected stored match through the shared series protocol."""
    from notebook_harness.stored_match import DEFAULT_API_BASE, load_stored_match

    mo.stop(not match_picker.value, mo.md("Pick a stored match to replay."))
    return load_stored_match(match_picker.value, api_base or DEFAULT_API_BASE)
