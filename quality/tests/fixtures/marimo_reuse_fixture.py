import marimo

__generated_with = "0.9.14"
app = marimo.App()

with app.setup:
    REUSABLE_PROBE_VALUE = 42


@app.class_definition
class ReusableProbe:
    """A pure class meant to be imported like a normal module attribute."""

    def __init__(self) -> None:
        self.value = REUSABLE_PROBE_VALUE


@app.cell
def _():
    # A regular, non-reusable cell. If marimo ever executed this on a plain
    # Python import, this test would fail loudly instead of silently passing.
    raise RuntimeError("This debug cell must never run on import.")
    return


if __name__ == "__main__":
    app.run()
