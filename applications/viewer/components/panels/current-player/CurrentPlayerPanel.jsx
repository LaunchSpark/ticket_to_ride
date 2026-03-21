import { h } from "../../runtime.jsx";
import { PLAYER_COLORS } from "../../constants.jsx";
import { CardShell } from "../../atoms/CardShell.jsx";
import { PlayerStatsPanel } from "../player-stats/PlayerStatsPanel.jsx";

function CurrentPlayerPanel(props) {
  const player = {
    ...props.player,
    positionLabel: "Current Player",
  };

  return h(
    CardShell,
    { className: "replay-current-player-panel" },
    h(PlayerStatsPanel, {
      player,
      accentColor: PLAYER_COLORS[props.player.meta.color] || props.player.meta.color || "#ff8f73",
    })
  );
}

export { CurrentPlayerPanel };
