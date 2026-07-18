// widget-src/src/spectate_shell_widget.js
// The viewer replay dashboard's grid, rebuilt around the existing route
// graph and info bar renderers. Layout mirrors replay-dashboard-grid:
// hero board + player sidebar on top, market / aggregates / tickets below.
import routeGraph from "./route_graph_widget.js";
import infoBar from "./info_bar_widget.js";

// Adapts the shell's model for an embedded widget whose render() expects
// its own trait names (the route graph reads `data`; the shell stores the
// same payload under `board`).
function facadeModel(model, mapping) {
    const mapKey = (key) => mapping[key] || key;
    return {
        get: (key) => model.get(mapKey(key)),
        set: (key, value) => model.set(mapKey(key), value),
        save_changes: () => model.save_changes(),
        on: (event, callback) => {
            const [kind, key] = event.split(":");
            model.on(key ? `${kind}:${mapKey(key)}` : event, callback);
        },
        off: (event, callback) => {
            const [kind, key] = event.split(":");
            model.off(key ? `${kind}:${mapKey(key)}` : event, callback);
        },
    };
}

function elem(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

function playbackOf(model) {
    const value = model.get("playback") || {};
    return { round: value.round || 0, turn: value.turn || 0 };
}

function frameOf(model) {
    return model.get("frame") || {};
}

function frameValue(model, key) {
    const frame = frameOf(model);
    return Object.prototype.hasOwnProperty.call(frame, key) ? frame[key] : model.get(key);
}

function displayedPlaybackOf(model) {
    const frame = frameOf(model);
    if (Number.isInteger(frame.round) && Number.isInteger(frame.turn)) {
        return { round: frame.round, turn: frame.turn };
    }
    return playbackOf(model);
}

function setPlayback(model, round, turn) {
    model.set("playback", { round, turn });
    model.save_changes();
}

function stepForward(model) {
    const meta = model.get("rounds_meta") || [];
    let { round, turn } = playbackOf(model);
    const turns = meta[round] ? meta[round].turnCount : 0;
    if (turn + 1 < turns) {
        setPlayback(model, round, turn + 1);
        return true;
    }
    if (round + 1 < meta.length) {
        setPlayback(model, round + 1, 0);
        return true;
    }
    return false;
}

function stepBack(model) {
    const meta = model.get("rounds_meta") || [];
    let { round, turn } = playbackOf(model);
    if (turn > 0) setPlayback(model, round, turn - 1);
    else if (round > 0) setPlayback(model, round - 1, meta[round - 1].turnCount - 1);
}

function renderSidebar(model, container, playState) {
    // Use the cursor bundled with the scores, not the optimistic JS cursor.
    // This keeps the heading and leaderboard on the same recorded turn while
    // Python is preparing the next frame.
    const { round, turn } = displayedPlaybackOf(model);

    // Keep controls mounted across frames. Replacing the pause button every
    // 300ms could destroy it between pointer-down and click, making playback
    // effectively impossible to stop.
    let header = container.querySelector(":scope > .shell-sidebar-header");
    if (!header) {
        header = elem("div", "shell-sidebar-header");
        header.appendChild(elem("p", "shell-eyebrow"));
        const controls = elem("div", "shell-playback-controls");
        const prev = elem("button", "shell-playback-button", "⏮");
        prev.addEventListener("click", () => stepBack(model));
        const play = elem("button", "shell-playback-button shell-play-toggle");
        play.addEventListener("click", () => playState.toggle());
        const next = elem("button", "shell-playback-button", "⏭");
        next.addEventListener("click", () => stepForward(model));
        controls.append(prev, play, next);
        header.appendChild(controls);

        const jump = elem("button", "shell-jump-button", "Jump To Round / Turn");
        jump.addEventListener("click", () => {
            const current = displayedPlaybackOf(model);
            const currentMeta = model.get("rounds_meta") || [];
            const roundPick = window.prompt(
                `Round (1-${currentMeta.length})`, String(current.round + 1)
            );
            if (roundPick == null) return;
            const target = Math.min(
                Math.max(parseInt(roundPick, 10) || 1, 1), currentMeta.length
            ) - 1;
            const turnPick = window.prompt(`Turn (1-${currentMeta[target].turnCount})`, "1");
            if (turnPick == null) return;
            const turnTarget = Math.min(
                Math.max(parseInt(turnPick, 10) || 1, 1), currentMeta[target].turnCount
            ) - 1;
            setPlayback(model, target, turnTarget);
        });
        header.appendChild(jump);

        const opacityControl = elem("label", "shell-opacity-control");
        const opacityCopy = elem("span", "shell-opacity-label", "Unclaimed opacity");
        const opacityOutput = elem("output", "shell-opacity-value");
        const opacitySlider = elem("input", "shell-opacity-slider");
        opacitySlider.type = "range";
        opacitySlider.min = "0";
        opacitySlider.max = "1";
        opacitySlider.step = "0.05";
        opacitySlider.addEventListener("input", () => {
            const value = Number(opacitySlider.value);
            opacityOutput.value = value.toFixed(2);
            opacityOutput.textContent = value.toFixed(2);
            model.set("unclaimed_route_opacity", value);
        });
        opacitySlider.addEventListener("change", () => model.save_changes());
        opacityControl.append(opacityCopy, opacityOutput, opacitySlider);
        header.appendChild(opacityControl);
        container.appendChild(header);
    }
    header.querySelector(".shell-eyebrow").textContent =
        `Round ${round + 1} · Turn ${turn + 1}`;
    header.querySelector(".shell-play-toggle").textContent = playState.playing ? "⏸" : "▶";
    const opacityValue = Number(model.get("unclaimed_route_opacity") ?? 0.5);
    const opacitySlider = header.querySelector(".shell-opacity-slider");
    const opacityOutput = header.querySelector(".shell-opacity-value");
    if (document.activeElement !== opacitySlider) opacitySlider.value = String(opacityValue);
    opacityOutput.value = opacityValue.toFixed(2);
    opacityOutput.textContent = opacityValue.toFixed(2);

    let board = container.querySelector(":scope > .shell-section");
    if (!board) {
        board = elem("div", "shell-section");
        container.appendChild(board);
    }
    board.replaceChildren(elem("p", "shell-section-heading", "Players"));
    const selected = model.get("selected_player") || "";
    const active = frameValue(model, "current_player") || "";
    (frameValue(model, "leaderboard") || []).forEach((entry) => {
        const card = renderPlayerCard(
            model,
            entry,
            entry.playerId === selected,
            entry.playerId === active,
        );
        // The same selection drives both the culled graph and ticket owner.
        // Clicking the selected card again returns to the full graph and the
        // active player's tickets.
        card.addEventListener("click", () => {
            const current = model.get("selected_player") || "";
            model.set("selected_player", current === entry.playerId ? "" : entry.playerId);
            model.save_changes();
        });
        board.appendChild(card);
    });
}

function renderPlayerCard(model, entry, selected, active) {
    const stats = (frameValue(model, "stats") || {})[entry.playerId];
    const card = elem("div", `shell-stats-card shell-player-card${selected ? " selected" : ""}`);
    card.style.setProperty("--accent", entry.color || "#888");
    const header = elem("div", "shell-player-card-header");
    header.appendChild(elem("span", "shell-leader-rank", String(entry.place).padStart(2, "0")));
    header.appendChild(elem("strong", "shell-leader-name", entry.name || entry.playerId));
    if (active) header.appendChild(elem("span", "shell-turn-badge", "TURN"));
    header.appendChild(elem("span", "shell-leader-score", String(entry.score)));
    card.appendChild(header);
    if (!stats) return card;
    const chips = elem("div", "shell-chip-row");
    chips.appendChild(elem("span", "shell-chip", `Trains ${stats.remainingTrains}`));
    chips.appendChild(elem("span", "shell-chip", `Tickets ${stats.ticketCount}`));
    chips.appendChild(elem("span", "shell-chip", `Routes ${stats.routeCount}`));
    if (stats.hiddenCards != null) chips.appendChild(elem("span", "shell-chip", `Hidden ${stats.hiddenCards}`));
    card.appendChild(chips);
    const hand = elem("div", "shell-hand-row");
    Object.entries(stats.hand || {}).forEach(([color, count]) => {
        const cell = elem("span", `shell-hand-cell hand-${color}`);
        cell.appendChild(elem("span", "shell-hand-dot"));
        cell.appendChild(elem("span", "shell-hand-count", String(count)));
        cell.title = color;
        hand.appendChild(cell);
    });
    card.appendChild(hand);
    return card;
}

function renderAggregates(model, container) {
    container.replaceChildren();
    container.appendChild(elem("p", "shell-section-heading", "Aggregate Stats"));
    const aggregates = model.get("aggregates") || [];
    const maxAverage = Math.max(1, ...aggregates.map((entry) => entry.averageScore));
    aggregates.forEach((entry) => {
        const row = elem("div", "shell-metric-row");
        row.style.setProperty("--accent", entry.color);
        row.appendChild(elem("strong", "shell-leader-name", entry.name));
        row.appendChild(
            elem("span", "shell-metric-values",
                `avg ${entry.averageScore} · best ${entry.bestScore} · wins ${entry.wins}`)
        );
        const bar = elem("div", "shell-metric-bar");
        bar.style.width = `${Math.max(8, (entry.averageScore / maxAverage) * 100)}%`;
        row.appendChild(bar);
        container.appendChild(row);
    });
}

function renderTickets(model, container) {
    container.replaceChildren();
    const ticketPlayer = frameValue(model, "ticket_player");
    const roster = (model.get("players") || []).find((player) => player.id === ticketPlayer) || {};
    const owner = roster.name ? ` · ${roster.name}` : "";
    container.appendChild(elem("p", "shell-section-heading", `Destination Tickets${owner}`));
    (frameValue(model, "tickets") || []).forEach((ticket, index) => {
        const row = elem("div", `shell-ticket-row status-${ticket.status}`);
        row.appendChild(elem("span", "shell-ticket-seq", `Ticket ${String(index + 1).padStart(2, "0")}`));
        row.appendChild(elem("strong", "shell-ticket-route", `${ticket.from} → ${ticket.to}`));
        const badge = ticket.status === "completed" ? "DONE"
            : ticket.status === "cut_off" ? "CUT OFF"
            : ticket.trainsShort != null ? `OPEN · ${ticket.trainsShort} to go` : "OPEN";
        row.appendChild(elem("span", "shell-ticket-badge", badge));
        row.appendChild(elem("span", "shell-ticket-points", `${ticket.points} pts`));
        container.appendChild(row);
    });
}

function render({ model, el }) {
    el.classList.add("spectate-shell");
    const grid = elem("div", "spectate-shell-grid");
    const hero = elem("section", "shell-slot-hero");
    const sidebar = elem("section", "shell-slot-sidebar");
    const market = elem("section", "shell-slot-market");
    const aggregates = elem("section", "shell-slot-current");
    const tickets = elem("section", "shell-slot-tickets");
    grid.append(hero, sidebar, market, aggregates, tickets);
    el.appendChild(grid);

    // Embedded renderers: the graph keeps its force-sim state because its
    // render mounts once here and reacts to trait changes itself.
    routeGraph.render({ model: facadeModel(model, { data: "board" }), el: hero });
    infoBar.render({ model: facadeModel(model, {}), el: market });

    let timer = null;
    const playState = {
        get playing() { return timer != null; },
        toggle() {
            if (timer != null) { clearInterval(timer); timer = null; }
            else {
                timer = setInterval(() => {
                    if (!stepForward(model)) { clearInterval(timer); timer = null; drawSidebar(); }
                }, model.get("interval_ms") || 300);
            }
            drawSidebar();
        },
    };

    const drawSidebar = () => renderSidebar(model, sidebar, playState);
    const drawAggregates = () => renderAggregates(model, aggregates);
    const drawTickets = () => renderTickets(model, tickets);

    drawSidebar();
    drawAggregates();
    drawTickets();
    model.on("change:frame", drawSidebar);
    model.on("change:frame", drawTickets);
    ["change:selected_player", "change:rounds_meta"]
        .forEach((event) => model.on(event, drawSidebar));
    model.on("change:aggregates", drawAggregates);
    model.on("change:tickets", drawTickets);

    return () => { if (timer != null) clearInterval(timer); };
}

export default { render };
