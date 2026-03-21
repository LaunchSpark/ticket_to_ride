import { h } from "../../runtime.jsx";
import { HAND_ORDER, PLAYER_COLORS } from "../../constants.jsx";

function PlayerStatsPanel(props) {
  const { player } = props;
  const knownCards = HAND_ORDER.map((color) => ({
    color,
    count: player.hand?.[color] ?? 0,
    accent: color === "locomotive" ? "linear-gradient(135deg, #ff8f73, #6e9bff, #3fff8b)" : PLAYER_COLORS[color],
  }));

  return h(
    "article",
    { className: "player-stats-panel" },
    h("span", {
      className: "scanner-row-accent player-stats-panel-accent",
      style: { background: props.accentColor },
    }),
    h(
      "div",
      { className: "player-stats-copy" },
      h(
        "div",
        { className: "player-stats-topline" },
        h("strong", { className: "player-stats-name" }, player.meta.name),
        h(
          "div",
          { className: "player-stats-header-metrics" },
          h("span", { className: "shell-chip" }, `Score ${player.score}`),
          h("span", { className: "shell-chip" }, `Unknown ${player.hand?.hidden ?? 0}`),
          h("span", { className: "shell-chip" }, `Trains ${player.remainingTrains}`),
          h("span", { className: "shell-chip" }, `Tickets ${player.destinationTicketCount ?? 0}`),
          h("span", { className: "shell-chip" }, `Routes ${(player.claimedRoutes || []).length}`)
        )
      )
    ),
    h(
      "div",
      { className: "player-stats-metrics" },
      knownCards.map((card) =>
        h(
          "div",
          { key: card.color, className: "player-stats-color-stat" },
          h("span", {
            className: "player-stats-color-chip",
            style: { background: card.accent || props.accentColor },
            title: card.color,
          }),
          h("span", { className: "player-stats-color-count" }, String(card.count))
        )
      )
    ),
  );
}

export { PlayerStatsPanel };
