import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from notebook_harness.spectate import replay_controls

    match_picker = replay_controls(mo)
    return match_picker, mo


@app.cell(hide_code=True)
def _(match_picker, mo):
    from notebook_harness.spectate import load_replay

    series = load_replay(mo, match_picker)
    return (series,)


@app.cell(hide_code=True)
def _(mo, series):
    from notebook_harness.spectate import spectate_widgets

    shell = spectate_widgets(mo, series)
    return (shell,)


@app.cell(hide_code=True)
def _(mo, series, shell):
    from notebook_harness.spectate import spectate_view

    spectate_view(mo, series, shell)
    return


if __name__ == "__main__":
    app.run()
