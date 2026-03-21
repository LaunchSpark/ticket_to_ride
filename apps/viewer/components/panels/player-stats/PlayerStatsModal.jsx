import { h } from "../../runtime.jsx";
import { PLAYER_COLORS } from "../../constants.jsx";
import { PlayerStatsPanel } from "./PlayerStatsPanel.jsx";
import { UiIcon } from "../../atoms/UiIcon.jsx";

function PlayerStatsModal(props) {
  if (!props.player) {
    return null;
  }

  return h(
    "div",
    { className: "player-stats-modal-backdrop", onClick: props.onClose },
    h(
      "div",
      {
        className: "player-stats-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": `${props.player.meta.name} detail`,
      },
      h(
        "div",
        { className: "panel-header panel-header-tight" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Player Stats"),
          h("h2", { className: "panel-title" }, props.player.meta.name)
        ),
        h(
          "button",
          {
            className: "player-stats-modal-close",
            type: "button",
            onClick: props.onClose,
            "aria-label": "Close player stats",
          },
          h(UiIcon, { name: "close" })
        )
      ),
      h(PlayerStatsPanel, {
        player: props.player,
        accentColor: PLAYER_COLORS[props.player.meta.color] || props.player.meta.color || "#ff8f73",
      })
    )
  );
}

export { PlayerStatsModal };
