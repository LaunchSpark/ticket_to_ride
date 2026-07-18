// widget-src/src/spectate_shell_widget.js
// The viewer replay dashboard's grid, rebuilt around the existing route
// graph and info bar renderers. Layout mirrors replay-dashboard-grid:
// hero board + sidebar on top, market / current player / tickets below.
import routeGraph from "./route_graph_widget.js";
import infoBar from "./info_bar_widget.js";
import { openStatsModal } from "./spectate_stats_modal.js";

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
    container.replaceChildren();
    const { round, turn } = playbackOf(model);
    const meta = model.get("rounds_meta") || [];

    const header = elem("div", "shell-sidebar-header");
    header.appendChild(elem("p", "shell-eyebrow", `Round ${round + 1} · Turn ${turn + 1}`));
    const controls = elem("div", "shell-playback-controls");
    const prev = elem("button", "shell-playback-button", "⏮");
    prev.addEventListener("click", () => stepBack(model));
    const play = elem("button", "shell-playback-button", playState.playing ? "⏸" : "▶");
    play.addEventListener("click", () => playState.toggle());
    const next = elem("button", "shell-playback-button", "⏭");
    next.addEventListener("click", () => stepForward(model));
    controls.append(prev, play, next);
    header.appendChild(controls);

    const jump = elem("button", "shell-jump-button", "Jump To Round / Turn");
    jump.addEventListener("click", () => {
        const roundPick = window.prompt(`Round (1-${meta.length})`, String(round + 1));
        if (roundPick == null) return;
        const target = Math.min(Math.max(parseInt(roundPick, 10) || 1, 1), meta.length) - 1;
        const turnPick = window.prompt(`Turn (1-${meta[target].turnCount})`, "1");
        if (turnPick == null) return;
        const turnTarget = Math.min(Math.max(parseInt(turnPick, 10) || 1, 1), meta[target].turnCount) - 1;
        setPlayback(model, target, turnTarget);
    });
    header.appendChild(jump);
    container.appendChild(header);

    const board = elem("div", "shell-section");
    board.appendChild(elem("p", "shell-section-heading", "Leaderboard"));
    const selected = model.get("selected_player") || "";
    (model.get("leaderboard") || []).forEach((entry) => {
        const row = elem("div", "shell-leader-row" + (entry.playerId === selected ? " selected" : ""));
        row.style.setProperty("--accent", entry.color);
        row.appendChild(elem("span", "shell-leader-rank", String(entry.place).padStart(2, "0")));
        const copy = elem("div", "shell-leader-copy");
        copy.appendChild(elem("strong", "shell-leader-name", entry.name));
        copy.appendChild(elem("span", "shell-leader-sub", `${entry.remainingTrains} trains left`));
        row.appendChild(copy);
        row.appendChild(elem("span", "shell-leader-score", String(entry.score)));
        const hands = elem("button", "shell-leader-hands", "🂠");
        hands.title = "View hand";
        hands.addEventListener("click", (event) => {
            event.stopPropagation();
            openStatsModal(model, container.closest(".spectate-shell"), entry.playerId);
        });
        row.appendChild(hands);
        // Row click = culling selection (same contract as PlayerListWidget)
        row.addEventListener("click", () => {
            const current = model.get("selected_player") || "";
            model.set("selected_player", current === entry.playerId ? "" : entry.playerId);
            model.save_changes();
        });
        board.appendChild(row);
    });
    container.appendChild(board);

    const details = elem("details", "shell-aggregates");
    details.appendChild(elem("summary", "shell-section-heading", "Aggregate Stats"));
    const maxAverage = Math.max(1, ...(model.get("aggregates") || []).map((a) => a.averageScore));
    (model.get("aggregates") || []).forEach((entry) => {
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
        details.appendChild(row);
    });
    container.appendChild(details);
}

function renderStatsCard(model, playerId) {
    const stats = (model.get("stats") || {})[playerId];
    const roster = (model.get("players") || []).find((p) => p.id === playerId) || {};
    const card = elem("div", "shell-stats-card");
    card.style.setProperty("--accent", roster.color || "#888");
    card.appendChild(elem("strong", "shell-leader-name", roster.name || playerId));
    if (!stats) return card;
    const chips = elem("div", "shell-chip-row");
    chips.appendChild(elem("span", "shell-chip", `Score ${stats.score}`));
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

function renderTickets(model, container) {
    container.replaceChildren();
    container.appendChild(elem("p", "shell-section-heading", "Destination Tickets"));
    (model.get("tickets") || []).forEach((ticket, index) => {
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
    const current = elem("section", "shell-slot-current");
    const tickets = elem("section", "shell-slot-tickets");
    grid.append(hero, sidebar, market, current, tickets);
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
    const drawCurrent = () => {
        current.replaceChildren();
        current.appendChild(elem("p", "shell-section-heading", "Current Player"));
        current.appendChild(renderStatsCard(model, model.get("current_player")));
    };
    const drawTickets = () => renderTickets(model, tickets);

    drawSidebar();
    drawCurrent();
    drawTickets();
    ["change:leaderboard", "change:playback", "change:aggregates", "change:selected_player", "change:rounds_meta"]
        .forEach((event) => model.on(event, drawSidebar));
    ["change:stats", "change:current_player"].forEach((event) => model.on(event, drawCurrent));
    model.on("change:tickets", drawTickets);

    return () => { if (timer != null) clearInterval(timer); };
}

export default { render };
export { renderStatsCard };
