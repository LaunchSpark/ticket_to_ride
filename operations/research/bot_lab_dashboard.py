import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup:
    import importlib.util
    import statistics
    from pathlib import Path

    import marimo as mo

    _here = Path(__file__).resolve().parent
    _spec = importlib.util.spec_from_file_location("bot_lab", _here / "bot_lab.py")
    bot_lab = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(bot_lab)

    # Chart palette: light-dark() follows the notebook theme (marimo sets
    # color-scheme on the root); chrome uses marimo's theme variables.
    _CHART_CSS = """
    <style>
    .botlab {
        --bl-blue: light-dark(#2a78d6, #3987e5);
        --bl-aqua: light-dark(#1baf7a, #199e70);
        --bl-yellow: light-dark(#eda100, #c98500);
        --bl-violet: light-dark(#4a3aa7, #9085e9);
        --bl-red: light-dark(#e34948, #e66767);
        --bl-orange: light-dark(#eb6834, #d95926);
        font-variant-numeric: tabular-nums;
    }
    .botlab svg text { fill: var(--muted-foreground, #52514e);
                       font: 11px ui-monospace, monospace; }
    .botlab svg text.val { fill: var(--foreground, #0b0b0b); font-weight: 600; }
    .botlab .zero { stroke: var(--border, #d5d4cf); }
    .botlab .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 11.5px;
                      color: var(--muted-foreground, #52514e); margin-top: 6px;
                      font-family: system-ui, sans-serif; }
    .botlab .legend span::before { content: ""; display: inline-block; width: 9px;
                      height: 9px; border-radius: 2px; margin-right: 5px;
                      background: var(--c); }
    </style>
    """


@app.function
def group_rows(rows):
    """(tag, opponent) -> [rows], sorted by key."""
    groups = {}
    for row in rows:
        groups.setdefault((row["tag"], row["opponent"]), []).append(row)
    return dict(sorted(groups.items()))


@app.function
def winrate_svg(groups):
    """Horizontal win-rate bars, direct-labeled (dataviz relief rule)."""
    row_h, width, label_w = 26, 460, 190
    parts = [f'<svg viewBox="0 0 {width} {len(groups) * row_h + 6}" style="width:100%">']
    for i, ((tag, opponent), games) in enumerate(groups.items()):
        rate = sum(g["won"] for g in games) / len(games)
        y = i * row_h + 4
        bar = max(2, (width - label_w - 50) * rate)
        parts.append(
            f'<text x="{label_w - 6}" y="{y + 13}" text-anchor="end">{tag} vs {opponent}</text>'
            f'<rect x="{label_w}" y="{y}" width="{bar:.1f}" height="16" rx="4"'
            f' style="fill: var(--bl-blue)"><title>{100 * rate:.0f}% of {len(games)} games</title></rect>'
            f'<text class="val" x="{label_w + bar + 6:.1f}" y="{y + 13}">{100 * rate:.0f}%</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


@app.function
def decomposition_svg(groups):
    """Diverging stacked bars: mean points earned right, penalties left."""
    row_h, width, label_w = 26, 500, 190
    mid = label_w + 120
    scale = 1.1
    parts = [f'<svg viewBox="0 0 {width} {len(groups) * row_h + 6}" style="width:100%">']
    parts.append(f'<line class="zero" x1="{mid}" y1="0" x2="{mid}" y2="{len(groups) * row_h + 4}"/>')
    for i, ((tag, opponent), games) in enumerate(groups.items()):
        y = i * row_h + 4
        mean = lambda key: statistics.mean(g["fable"].get(key, 0) for g in games)  # noqa: E731
        segments = [
            ("routes", mean("route_pts"), "--bl-yellow", +1),
            ("tickets completed", mean("tickets_completed_pts"), "--bl-aqua", +1),
            ("longest path", 10 * statistics.mean(g["fable"]["longest_path"] for g in games), "--bl-violet", +1),
            ("impossible", mean("tickets_impossible_pts"), "--bl-red", -1),
            ("pending", mean("tickets_pending_pts"), "--bl-orange", -1),
        ]
        parts.append(f'<text x="{label_w - 6}" y="{y + 13}" text-anchor="end">{tag} vs {opponent}</text>')
        pos = neg = mid
        for name, value, color, sign in segments:
            span = abs(value) * scale
            if span < 0.5:
                continue
            x = pos if sign > 0 else neg - span
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{max(1.0, span - 2):.1f}" height="16" rx="3"'
                f' style="fill: var({color})"><title>{name}: {sign * value:+.1f} pts/game</title></rect>'
            )
            if sign > 0:
                pos += span
            else:
                neg -= span
    parts.append("</svg>")
    return "".join(parts)


@app.function
def margins_svg(groups, rows):
    """One dot per game; wins blue, losses red, vertical line at zero."""
    row_h, width, label_w = 30, 500, 190
    margins = [r["margin"] for r in rows] or [0]
    lo, hi = min(-10, *margins), max(10, *margins)
    x = lambda m: label_w + (m - lo) / (hi - lo) * (width - label_w - 12)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {width} {len(groups) * row_h + 20}" style="width:100%">']
    parts.append(f'<line class="zero" x1="{x(0):.1f}" y1="0" x2="{x(0):.1f}" y2="{len(groups) * row_h}"/>')
    for i, ((tag, opponent), games) in enumerate(groups.items()):
        y = i * row_h + 15
        parts.append(f'<text x="{label_w - 6}" y="{y + 4}" text-anchor="end">{tag} vs {opponent}</text>')
        for j, g in enumerate(games):
            color = "--bl-blue" if g["won"] else "--bl-red"
            jitter = ((j % 5) - 2) * 2.4
            parts.append(
                f'<circle cx="{x(g["margin"]):.1f}" cy="{y + jitter:.1f}" r="3.4"'
                f' style="fill: var({color}); fill-opacity: 0.75;'
                f' stroke: var(--background, #fff); stroke-width: 1">'
                f'<title>seed {g["seed"]}: {g["margin"]:+d}</title></circle>'
            )
    parts.append(f'<text x="{x(0):.1f}" y="{len(groups) * row_h + 16}" text-anchor="middle">0</text>')
    parts.append("</svg>")
    return "".join(parts)


@app.cell(hide_code=True)
def _():
    mo.md(
        """
    # Fable Bot Lab
    Seeded duels with alternating seats; every heuristic configuration is a
    tagged run. Results accumulate in `results/games.jsonl` — the CLI
    (`bot_lab.py`) and this dashboard read and write the same file.
    """
    ).left()
    return


@app.cell(hide_code=True)
def _():
    games_slider = mo.ui.slider(10, 100, step=10, value=40, label="Games per opponent")
    opponent_picker = mo.ui.multiselect(
        options=sorted(bot_lab.OPPONENTS), value=["qualifier", "example"], label="Opponents"
    )
    tag_field = mo.ui.text(value="baseline", label="Config tag")
    overrides_field = mo.ui.text(
        placeholder="_ENDGAME_TURNS=10, _LOCO_OPTION_COST=0.5",
        label="Heuristic overrides",
        full_width=True,
    )
    run_button = mo.ui.run_button(label="Run tournament")
    mo.vstack([
        mo.hstack([games_slider, opponent_picker, tag_field], align="end", justify="start"),
        mo.hstack([overrides_field, run_button], align="end", justify="start"),
    ])
    return games_slider, opponent_picker, overrides_field, run_button, tag_field


@app.cell(hide_code=True)
def _(games_slider, opponent_picker, overrides_field, run_button, tag_field):
    run_stamp = 0
    if run_button.value:
        pairs = [p.strip() for p in overrides_field.value.split(",") if p.strip()]
        overrides = bot_lab.parse_overrides(pairs)
        variant = bot_lab.build_variant(overrides)
        fresh_rows = []
        fresh_events = []
        for opponent in opponent_picker.value:
            _rows, _events = bot_lab.run_matchup(
                tag_field.value or "untagged", variant,
                opponent, games_slider.value, 9000,
            )
            fresh_rows.extend(_rows)
            fresh_events.extend(_events)
        bot_lab.append_rows(fresh_rows)
        bot_lab.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with bot_lab.CLAIMS_FILE.open("a") as _handle:
            for _event in fresh_events:
                _handle.write(bot_lab.json.dumps(_event) + "\n")
        run_stamp = len(fresh_rows)
    return (run_stamp,)


@app.cell(hide_code=True)
def _(run_stamp):
    _ = run_stamp  # rerun after every tournament
    rows = bot_lab.load_all_rows()
    mo.stop(
        not rows,
        mo.md("*No results yet — run a tournament above, or use the CLI:*"
              " `uv run python operations/research/bot_lab.py --games 40`"),
    )
    groups = group_rows(rows)
    return groups, rows

@app.cell(hide_code=True)
def _(rows):
    wins = sum(r["won"] for r in rows)
    mo.hstack(
        [
            mo.stat(len(rows), label="games"),
            mo.stat(f"{100 * wins / len(rows):.0f}%", label="win rate"),
            mo.stat(f"{statistics.mean(r['margin'] for r in rows):+.1f}", label="avg margin"),
            mo.stat(f"{statistics.mean(r['fable']['score'] for r in rows):.1f}", label="avg score"),
            mo.stat(len({r["tag"] for r in rows}), label="configs"),
        ],
        justify="start",
        gap=2,
    )
    return


@app.cell(hide_code=True)
def _(groups, rows):
    _legend = (
        '<div class="legend">'
        '<span style="--c: var(--bl-yellow)">routes</span>'
        '<span style="--c: var(--bl-aqua)">tickets completed</span>'
        '<span style="--c: var(--bl-violet)">longest path</span>'
        '<span style="--c: var(--bl-red)">impossible</span>'
        '<span style="--c: var(--bl-orange)">pending</span>'
        "</div>"
    )
    mo.vstack([
        mo.md("### Win rate"),
        mo.Html(f'{_CHART_CSS}<div class="botlab">{winrate_svg(groups)}</div>'),
        mo.md("### Mean score decomposition (points per game; penalties left of zero)"),
        mo.Html(f'<div class="botlab">{decomposition_svg(groups)}{_legend}</div>'),
        mo.md("### Margin per game"),
        mo.Html(f'<div class="botlab">{margins_svg(groups, rows)}</div>'),
    ])
    return


@app.cell(hide_code=True)
def _(rows):
    _tags = sorted({r["tag"] for r in rows})
    _params = sorted({k for r in rows for k in (r.get("config") or {})})
    _config_rows = [
        {
            "parameter": p.strip("_").lower().replace("_", " "),
            **{
                t: next((r["config"].get(p, "–") for r in rows if r["tag"] == t and r.get("config")), "–")
                for t in _tags
            },
        }
        for p in _params
    ]
    mo.vstack([mo.md("### Heuristic configurations"), mo.ui.table(_config_rows, selection=None)])
    return


@app.cell(hide_code=True)
def _(rows):
    _game_rows = [
        {
            "tag": r["tag"],
            "opponent": r["opponent"],
            "seed": r["seed"],
            "result": "W" if r["won"] else "L",
            "margin": r["margin"],
            "score": r["fable"]["score"],
            "routes": r["fable"]["route_pts"],
            "tickets +": r["fable"]["tickets_completed_pts"],
            "impossible −": r["fable"]["tickets_impossible_pts"],
            "pending −": r["fable"]["tickets_pending_pts"],
            "LP": "✓" if r["fable"]["longest_path"] else "",
            "kept": r["fable"]["tickets_kept"],
            "trains left": r["fable"]["trains_left"],
            "loco takes": r["fable"].get("loco_takes", 0),
            "turns": r["turns"],
        }
        for r in sorted(rows, key=lambda r: r["margin"])
    ]
    mo.vstack([mo.md("### Games (sorted by margin)"), mo.ui.table(_game_rows, selection=None)])
    return


if __name__ == "__main__":
    app.run()
