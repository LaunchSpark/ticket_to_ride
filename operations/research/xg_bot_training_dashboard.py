import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")

with app.setup:
    import importlib.util
    import json
    import math
    import sys
    import time
    from pathlib import Path

    import marimo as mo

    REPO = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(REPO / "integrations"))

    _here = Path(__file__).resolve().parent
    _spec = importlib.util.spec_from_file_location("train_xg_bot", _here / "train_xg_bot.py")
    train_xg_bot = importlib.util.module_from_spec(_spec)
    sys.modules["train_xg_bot"] = train_xg_bot
    _spec.loader.exec_module(train_xg_bot)
    _pump_spec = importlib.util.spec_from_file_location("xg_data_pump", _here / "xg_data_pump.py")
    xg_data_pump = importlib.util.module_from_spec(_pump_spec)
    sys.modules["xg_data_pump"] = xg_data_pump
    _pump_spec.loader.exec_module(xg_data_pump)

    from external.ml import xgb_features
    from wigglystuff import ProgressBar

    DEFAULT_RECORDS = REPO / "operations" / "research" / "results" / "records.jsonl"
    DEFAULT_DECISIONS = REPO / "operations" / "research" / "results" / "decisions.jsonl"
    DEFAULT_FEATURE_ROWS = REPO / "operations" / "research" / "results" / "xg_pump_feature_rows.jsonl"
    DEFAULT_SUMMARIES = REPO / "operations" / "research" / "results" / "xg_pump_games.jsonl"
    DEFAULT_MODEL = REPO / "operations" / "research" / "results" / "xg_bot_ranker.json"
    DEFAULT_FEATURES = REPO / "operations" / "research" / "results" / "xg_bot_features.json"

    CHART_CSS = """
    <style>
    .xgbdash { --xg-blue: light-dark(#2a78d6, #4d9af0);
               --xg-aqua: light-dark(#1baf7a, #31c58f);
               --xg-grid: light-dark(#dad8d2, #34383f);
               font-variant-numeric: tabular-nums; }
    .xgbdash svg text { fill: var(--muted-foreground, #52514e);
                        font: 11px ui-monospace, monospace; }
    .xgbdash svg .axis { stroke: var(--xg-grid); stroke-width: 1; }
    .xgbdash svg .line-top1 { fill: none; stroke: var(--xg-blue); stroke-width: 2.5; }
    .xgbdash svg .line-mrr { fill: none; stroke: var(--xg-aqua); stroke-width: 2.0; stroke-dasharray: 4 4; }
    .xgbdash .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 11.5px;
                       color: var(--muted-foreground, #52514e); margin-top: 6px;
                       font-family: system-ui, sans-serif; }
    .xgbdash .legend span::before { content: ""; display: inline-block; width: 10px;
                       height: 10px; border-radius: 2px; margin-right: 5px; background: var(--c); }
    </style>
    """


@app.function
def pump_curve_svg(history):
    games = history.get("game", [])
    if not games:
        return ""

    top1 = history.get("top1", [])
    mrr = history.get("mrr", [])
    width, height = 680, 240
    left, right, top, bottom = 58, 18, 18, 42
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_game = max(games) if max(games) > 0 else 1

    def x_of(game_number):
        return left + (game_number / max_game) * plot_w

    def y_of(value):
        return top + (1.0 - value) * plot_h

    def polyline(series):
        points = [
            f"{x_of(games[index]):.1f},{y_of(value):.1f}"
            for index, value in enumerate(series)
            if value is not None and math.isfinite(value)
        ]
        return " ".join(points)

    parts = [f'<svg viewBox="0 0 {width} {height}" style="width:100%; max-width:{width}px">']
    parts.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}"/>')
    for value in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = y_of(value)
        parts.append(f'<line class="axis" x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" opacity="0.35"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{value:.2f}</text>')
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        game_label = int(max_game * frac)
        x = left + plot_w * frac
        parts.append(f'<text x="{x:.1f}" y="{height - 16}" text-anchor="middle">{game_label}</text>')
    if top1:
        parts.append(f'<polyline class="line-top1" points="{polyline(top1)}"><title>top-1 accuracy</title></polyline>')
    if mrr:
        parts.append(f'<polyline class="line-mrr" points="{polyline(mrr)}"><title>mean reciprocal rank</title></polyline>')
    parts.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 2}" text-anchor="middle">generated games</text>')
    parts.append("</svg>")
    return "".join(parts)


@app.function
def render_pump_panel(history, status):
    latest = {key: values[-1] for key, values in history.items() if values}
    top1 = latest.get("top1")
    mrr = latest.get("mrr")
    stats = [
        mo.stat(latest.get("game", 0), label="games"),
        mo.stat(latest.get("decisions", 0), label="Qualifier decisions"),
        mo.stat("-" if top1 is None else f"{top1:.3f}", label="top-1"),
        mo.stat("-" if mrr is None else f"{mrr:.3f}", label="MRR"),
    ]
    return mo.vstack([
        mo.hstack(stats, justify="start"),
        mo.Html(
            CHART_CSS
            + '<div class="xgbdash">'
            + pump_curve_svg(history)
            + '<div class="legend">'
            + '<span style="--c: var(--xg-blue)">top-1 accuracy</span>'
            + '<span style="--c: var(--xg-aqua)">MRR</span>'
            + "</div></div>"
        ),
        mo.md(status),
    ])


@app.function
def save_feature_schema(path, schema, model_path, train_report):
    payload = {
        "schema_version": 1,
        "created_at_unix": int(time.time()),
        "feature_names": schema,
        "model_path": str(model_path),
        "train_report": train_report,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


@app.cell(hide_code=True)
def _():
    mo.md(
        """
    # XG Bot classic pump
    Generate classic-map games, mix in non-Qualifier seats for state variety,
    capture only `QualifierBot` decisions, cache their feature groups, and
    checkpoint-train the XG ranker every N captured decisions.
    """
    ).left()
    return


@app.cell(hide_code=True)
def _():
    pump_games = mo.ui.number(start=1, stop=1_000_000, step=100, value=10_000, label="Games")
    pump_train_every_decisions = mo.ui.number(
        start=100,
        stop=10_000_000,
        step=1_000,
        value=10_000,
        label="Train every Qualifier decisions",
    )
    pump_progress_every = mo.ui.number(start=1, stop=50_000, step=10, value=10, label="Progress every games")
    pump_boost_rounds = mo.ui.slider(10, 400, step=10, value=80, label="Boost rounds per checkpoint")
    pump_min_players = mo.ui.slider(2, 5, step=1, value=2, label="Min players")
    pump_max_players = mo.ui.slider(2, 5, step=1, value=5, label="Max players")
    pump_nonqual = mo.ui.slider(0.0, 1.0, step=0.05, value=0.25, label="Non-Qualifier seat chance")
    pump_seed_base = mo.ui.number(start=1, stop=2_000_000_000, step=1, value=100_000, label="Seed base")
    pump_db_mode = mo.ui.dropdown(
        options=["db if available", "require db", "jsonl only"],
        value="db if available",
        label="Persistence",
    )
    pump_decisions_path = mo.ui.text(value=str(DEFAULT_DECISIONS), label="Qualifier decisions JSONL", full_width=True)
    pump_feature_rows_path = mo.ui.text(value=str(DEFAULT_FEATURE_ROWS), label="Cached feature groups JSONL", full_width=True)
    pump_model_path = mo.ui.text(value=str(DEFAULT_MODEL), label="Model output", full_width=True)
    pump_features_path = mo.ui.text(value=str(DEFAULT_FEATURES), label="Feature schema output", full_width=True)
    pump_button = mo.ui.run_button(label="Run classic pump")
    mo.vstack([
        mo.hstack([pump_games, pump_train_every_decisions, pump_progress_every, pump_boost_rounds], align="end", justify="start"),
        mo.hstack([pump_min_players, pump_max_players, pump_nonqual, pump_seed_base], align="end", justify="start"),
        mo.hstack([pump_db_mode, pump_button], align="end", justify="start"),
        pump_decisions_path,
        pump_feature_rows_path,
        pump_model_path,
        pump_features_path,
    ])
    return (
        pump_boost_rounds,
        pump_button,
        pump_db_mode,
        pump_decisions_path,
        pump_feature_rows_path,
        pump_features_path,
        pump_games,
        pump_max_players,
        pump_min_players,
        pump_model_path,
        pump_nonqual,
        pump_progress_every,
        pump_seed_base,
        pump_train_every_decisions,
    )


@app.cell(hide_code=True)
def _(
    pump_boost_rounds,
    pump_button,
    pump_db_mode,
    pump_decisions_path,
    pump_feature_rows_path,
    pump_features_path,
    pump_games,
    pump_max_players,
    pump_min_players,
    pump_model_path,
    pump_nonqual,
    pump_progress_every,
    pump_seed_base,
    pump_train_every_decisions,
):
    mo.stop(
        not pump_button.value,
        mo.md("Press **Run classic pump** to generate classic-map games and checkpoint-train the XG Bot."),
    )

    try:
        import xgboost as pump_xgb
    except ImportError:
        mo.stop(
            True,
            mo.md("Install the optional dependencies first: `uv sync --extra xgb`, or launch with `--extra xgb`."),
        )

    total_games = int(pump_games.value)
    pump_train_decision_interval = max(1, int(pump_train_every_decisions.value))
    pump_progress_interval = max(1, int(pump_progress_every.value))
    min_players = int(pump_min_players.value)
    max_players = int(pump_max_players.value)
    mo.stop(min_players > max_players, mo.md("*Min players must be less than or equal to max players.*"))

    pump_history = {"game": [], "top1": [], "mrr": [], "decisions": []}
    total_decisions = 0
    pump_started = time.perf_counter()
    pump_progress_bar = mo.ui.anywidget(
        ProgressBar(
            value=0,
            max_value=total_games,
            color="#2a78d6",
            show_text=True,
            height=22,
        )
    )
    mo.output.replace(
        mo.vstack([
            pump_progress_bar,
            render_pump_panel(
                pump_history,
                f"Starting classic pump for {total_games} games. Checking persistence and loading bots...",
            ),
        ])
    )

    db_mode = pump_db_mode.value
    db_available = True
    if db_mode == "db if available":
        try:
            xg_data_pump.GameLogger([]).list_matches()
        except Exception:
            db_available = False
    no_db = db_mode == "jsonl only" or (db_mode == "db if available" and not db_available)
    require_db = db_mode == "require db"

    qualifier, alternatives = xg_data_pump.load_bot_pool()
    pump_schema = xgb_features.feature_names()
    pump_params = {
        "objective": "rank:pairwise",
        "eval_metric": "ndcg@1",
        "eta": 0.05,
        "max_depth": 4,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "tree_method": "hist",
        "seed": int(pump_seed_base.value),
    }
    pump_model_out = Path(pump_model_path.value).expanduser()
    pump_features_out = Path(pump_features_path.value).expanduser()
    pump_decisions_out = Path(pump_decisions_path.value).expanduser()
    pump_feature_rows_out = Path(pump_feature_rows_path.value).expanduser()
    records_out = DEFAULT_RECORDS
    summaries_out = DEFAULT_SUMMARIES
    pump_booster = None
    pending_cached_groups = []
    pending_decision_count = 0

    for offset in range(total_games):
        game_number = offset + 1
        result = xg_data_pump.run_generated_game(
            seed=int(pump_seed_base.value) + offset,
            qualifier=qualifier,
            alternatives=alternatives,
            min_players=min_players,
            max_players=max_players,
            non_qualifier_probability=float(pump_nonqual.value),
            require_db=require_db,
            no_db=no_db,
            tag="xg-notebook-pump",
        )
        pump_cached_groups = xg_data_pump.cached_rank_groups_from_decisions(
            result["decisions"],
            schema=pump_schema,
        )
        xg_data_pump.append_jsonl(records_out, [result["record"]])
        xg_data_pump.append_jsonl(pump_decisions_out, result["decisions"])
        xg_data_pump.append_jsonl(pump_feature_rows_out, pump_cached_groups)
        xg_data_pump.append_jsonl(summaries_out, [result["summary"]])
        pending_cached_groups.extend(pump_cached_groups)
        captured_decisions = len(pump_cached_groups)
        pending_decision_count += captured_decisions
        total_decisions += captured_decisions
        pump_progress_bar.value = game_number

        should_train = (
            pending_decision_count >= pump_train_decision_interval
            or (game_number == total_games and pending_cached_groups)
        )
        if not should_train:
            if game_number % pump_progress_interval == 0 or game_number == total_games:
                pump_history["game"].append(game_number)
                pump_history["top1"].append(None)
                pump_history["mrr"].append(None)
                pump_history["decisions"].append(total_decisions)
                persistence = "DB + JSONL" if not no_db else "JSONL only"
                mo.output.replace(
                    mo.vstack([
                        pump_progress_bar,
                        render_pump_panel(
                            pump_history,
                            f"Generating classic games: {game_number}/{total_games}. "
                            f"{total_decisions} Qualifier decisions cached, persistence={persistence}. "
                            f"Next training checkpoint after "
                            f"{max(0, pump_train_decision_interval - pending_decision_count)} more Qualifier decisions.",
                        ),
                    ])
                )
            continue

        pump_matrix, pump_labels, pump_group_sizes, pump_groups = train_xg_bot.build_cached_rank_dataset(
            pending_cached_groups,
            schema=pump_schema,
        )
        pump_dmatrix = pump_xgb.DMatrix(pump_matrix, label=pump_labels)
        pump_dmatrix.set_group(pump_group_sizes)
        pump_booster = pump_xgb.train(
            pump_params,
            pump_dmatrix,
            num_boost_round=int(pump_boost_rounds.value),
            xgb_model=pump_booster,
            verbose_eval=False,
        )
        report = train_xg_bot.rank_report_from_scores(
            pump_booster.predict(pump_dmatrix),
            pump_groups,
            len(pump_labels),
        )
        pump_model_out.parent.mkdir(parents=True, exist_ok=True)
        pump_booster.save_model(str(pump_model_out))
        save_feature_schema(pump_features_out, pump_schema, pump_model_out, report)

        pump_history["game"].append(game_number)
        pump_history["top1"].append(report["top1_accuracy"])
        pump_history["mrr"].append(report["mean_reciprocal_rank"])
        pump_history["decisions"].append(total_decisions)
        pending_cached_groups.clear()
        pending_decision_count = 0
        persistence = "DB + JSONL" if not no_db else "JSONL only"
        mo.output.replace(
            mo.vstack([
                pump_progress_bar,
                render_pump_panel(
                    pump_history,
                    f"Running classic pump: {game_number}/{total_games} games, "
                    f"{total_decisions} Qualifier decisions cached, persistence={persistence}. "
                    f"Saved `{pump_model_out}`.",
                ),
            ])
        )

    pump_elapsed = time.perf_counter() - pump_started
    mo.vstack([
        pump_progress_bar,
        render_pump_panel(
            pump_history,
            f"Done: {total_games} classic games in {pump_elapsed:.1f}s. "
            f"Cached `{pump_feature_rows_out}`. Saved `{pump_model_out}` and `{pump_features_out}`.",
        ),
        mo.md("### Pump checkpoints"),
        mo.ui.table([
            {
                "game": pump_history["game"][index],
                "Qualifier decisions": pump_history["decisions"][index],
                "top1": pump_history["top1"][index],
                "mrr": pump_history["mrr"][index],
            }
            for index in range(len(pump_history["game"]))
        ], selection=None),
    ])
    return


if __name__ == "__main__":
    app.run()
