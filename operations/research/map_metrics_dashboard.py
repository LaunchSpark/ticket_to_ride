import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup:
    import importlib.util
    from pathlib import Path

    import marimo as mo

    _here = Path(__file__).resolve().parent
    _spec = importlib.util.spec_from_file_location("map_eval", _here / "map_eval.py")
    map_eval = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(map_eval)

    from notebook_harness.game_runner import list_maps

    _CHART_CSS = """
    <style>
    .mapeval { --me-blue: light-dark(#2a78d6, #3987e5);
               --me-aqua: light-dark(#1baf7a, #199e70);
               font-variant-numeric: tabular-nums; }
    .mapeval svg text { fill: var(--muted-foreground, #52514e);
                        font: 11px ui-monospace, monospace; }
    .mapeval svg text.val { fill: var(--foreground, #0b0b0b); font-weight: 600; }
    .mapeval .zero { stroke: var(--border, #d5d4cf); }
    </style>
    """

    # Gauntlet metrics worth comparing across maps, with display ranges.
    _COMPARE = [
        ("seat0_win_rate", 0.0, 1.0),
        ("ticket_completion_rate", 0.0, 1.0),
        ("ticket_impossible_rate", 0.0, 0.5),
        ("routes_used_fraction", 0.0, 1.0),
        ("claim_entropy", 0.0, 1.0),
        ("critical_claim_fraction", 0.0, 1.0),
    ]


@app.function
def compare_svg(profiles):
    """Normalized horizontal bars: one row per metric, one bar per map."""
    colors = ["--me-blue", "--me-aqua"]
    row_h, bar_h, width, label_w = 16 + 14 * len(profiles), 12, 460, 190
    parts = [f'<svg viewBox="0 0 {width} {len(_COMPARE) * row_h + 6}" style="width:100%">']
    for i, (key, lo, hi) in enumerate(_COMPARE):
        y = i * row_h + 4
        parts.append(f'<text x="{label_w - 6}" y="{y + 10}" text-anchor="end">{key}</text>')
        for j, profile in enumerate(profiles):
            value = profile["gameplay"][key]
            frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
            bar = max(2, (width - label_w - 60) * frac)
            by = y + j * (bar_h + 2)
            color = colors[j % len(colors)]
            parts.append(
                f'<rect x="{label_w}" y="{by}" width="{bar:.1f}" height="{bar_h}" rx="3"'
                f' style="fill: var({color})"><title>{profile["map"]}: {value}</title></rect>'
                f'<text class="val" x="{label_w + bar + 6:.1f}" y="{by + 10}">'
                f'{profile["map"]} {value}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


@app.cell(hide_code=True)
def _():
    mo.md(
        """
    # Map Metrics — the two loops
    **Loop 1 (structural realism)** asks *does this look like a Ticket to Ride
    map?* — handcrafted descriptors over the graph and tickets. **Loop 2
    (gameplay quality)** asks *does it play balanced?* — emergent metrics from
    QualifierBot mirror matches (self-play, so any bias is the map's fault).
    Human maps define the target bands; profiles accumulate in
    `results/map_profiles.jsonl` for the future surrogate critic and the
    novelty archive.
    """
    ).left()
    return


@app.cell(hide_code=True)
def _():
    map_picker = mo.ui.multiselect(options=list_maps(), value=list_maps(), label="Maps")
    games_slider = mo.ui.slider(10, 200, step=10, value=40, label="Gauntlet games")
    profile_button = mo.ui.run_button(label="Profile maps")
    mo.hstack([map_picker, games_slider, profile_button], align="end", justify="start")
    return games_slider, map_picker, profile_button


@app.cell(hide_code=True)
def _(games_slider, map_picker, profile_button):
    profile_stamp = 0
    if profile_button.value:
        for _map_name in map_picker.value:
            map_eval.append_profile(
                map_eval.map_profile(_map_name, games_slider.value)
            )
            profile_stamp += 1
    return (profile_stamp,)


@app.cell(hide_code=True)
def _(profile_stamp):
    _ = profile_stamp
    all_profiles = map_eval.load_profiles()
    mo.stop(
        not all_profiles,
        mo.md("*No profiles yet — press **Profile maps**, or run the CLI:*"
              " `uv run python operations/research/map_eval.py`"),
    )
    # latest profile per map wins the comparison view
    latest = {}
    for _profile in all_profiles:
        latest[_profile["map"]] = _profile
    profiles = list(latest.values())
    return (profiles,)


@app.cell(hide_code=True)
def _(profiles):
    mo.vstack([
        mo.md("### Gameplay comparison (Loop 2 — QualifierBot mirror gauntlet)"),
        mo.Html(f'{_CHART_CSS}<div class="mapeval">{compare_svg(profiles)}</div>'),
    ])
    return


@app.cell(hide_code=True)
def _(profiles):
    _rows = []
    for _section in ("structural", "gameplay"):
        _keys = sorted({k for p in profiles for k in p[_section]})
        for _key in _keys:
            if _key in ("color_demand", "most_contested", "route_length_hist", "games"):
                continue
            _rows.append({
                "metric": f"{_section}.{_key}",
                **{p["map"]: p[_section].get(_key) for p in profiles},
            })
    mo.vstack([mo.md("### MapProfile — full descriptor table"), mo.ui.table(_rows, selection=None)])
    return


@app.cell(hide_code=True)
def _(profiles):
    _rows = [
        {"map": p["map"],
         "most contested routes": ", ".join(p["gameplay"]["most_contested"]),
         "route length histogram": str(p["structural"]["route_length_hist"]),
         "color demand (claimed length)": str(p["gameplay"]["color_demand"])}
        for p in profiles
    ]
    mo.vstack([mo.md("### Hotspots and distributions"), mo.ui.table(_rows, selection=None)])
    return


if __name__ == "__main__":
    app.run()
