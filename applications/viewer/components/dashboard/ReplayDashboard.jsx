import { h, useDeferredValue, useMemo, useState } from "../runtime.jsx";
import { StatusScreen } from "../atoms/StatusScreen.jsx";
import { buildReplayModel } from "../model/replay-model.jsx";
import { CurrentPlayerPanel } from "../panels/current-player/CurrentPlayerPanel.jsx";
import { DestinationTicketsPanel } from "../panels/destination-tickets/DestinationTicketsPanel.jsx";
import { MapRoutesPanel } from "../panels/map-routes/MapRoutesPanel.jsx";
import { MarketStrip } from "../panels/market/MarketStrip.jsx";
import { MatchSidebarPanel } from "../panels/match-sidebar/MatchSidebarPanel.jsx";
import { PlayerStatsModal } from "../panels/player-stats/PlayerStatsModal.jsx";

function ReplayDashboard(props) {
  const deferredTurnIndex = useDeferredValue(props.playback.turnIndex);
  const [selectedPlayerId, setSelectedPlayerId] = useState(null);
  const model = useMemo(
    () => buildReplayModel(props.matchData, props.playback.roundIndex, deferredTurnIndex),
    [props.matchData, props.playback.roundIndex, deferredTurnIndex]
  );

  const selectedPlayer = useMemo(() => {
    if (!model || !selectedPlayerId) {
      return null;
    }

    return [model.currentPlayer]
      .concat(model.peripheralPlayers)
      .find((player) => player.playerId === selectedPlayerId) || null;
  }, [model, selectedPlayerId]);

  if (!model) {
    return h(StatusScreen, {
      label: "Replay Status",
      title: "No Replay Data Yet",
      message: "This match does not have any turns available yet.",
    });
  }

  return h(
    "div",
    { className: "replay-dashboard-grid" },
    h("section", {
      className: "grid-slot-hero",
    }, h(MapRoutesPanel, {
      model,
      routeMarkup: props.routeMarkup,
    })),
    h("section", { className: "grid-slot-sidebar" }, h(MatchSidebarPanel, {
      model,
      roundNumber: props.roundNumber,
      turnNumber: props.turnNumber,
      isRunning: props.isRunning,
      onPrev: props.onPrev,
      onNext: props.onNext,
      onTogglePlay: props.onTogglePlay,
      onJumpTo: props.onJumpTo,
      canStepBack: props.canStepBack,
      canStepForward: props.canStepForward,
      onToggleMenu: props.onToggleMenu,
      onSelectPlayer: setSelectedPlayerId,
    })),
    h("section", { className: "grid-slot-market" }, h(MarketStrip, { marketCards: model.marketCards })),
    h("section", { className: "grid-slot-current" }, h(CurrentPlayerPanel, {
      player: model.currentPlayer,
      cardCounts: model.cardCounts,
    })),
    h("section", { className: "grid-slot-tickets" }, h(DestinationTicketsPanel, {
      player: model.currentPlayer,
      tickets: model.tickets,
    })),
    h(PlayerStatsModal, {
      player: selectedPlayer,
      onClose: () => setSelectedPlayerId(null),
    })
  );
}

export { ReplayDashboard };
