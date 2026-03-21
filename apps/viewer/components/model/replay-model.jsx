import {
  CURRENT_PLAYER_CARD_IMAGES,
  HAND_ORDER,
  PLAYER_COLORS,
  POSITION_LABELS,
  resolveTrainCardImage,
} from "../constants.jsx";

function normalizeClaimedRoute(claimedRoute) {
  if (!claimedRoute) {
    return {
      routeId: "",
      routeLabel: "",
    };
  }

  if (typeof claimedRoute === "string") {
    return {
      routeId: claimedRoute,
      routeLabel: claimedRoute,
    };
  }

  return {
    routeId: claimedRoute.routeId || claimedRoute.routeLabel || "",
    routeLabel: claimedRoute.routeLabel || claimedRoute.routeId || "",
  };
}

function buildReplayModel(matchData, roundIndex, turnIndex) {
  const rounds = matchData?.rounds || [];
  if (!matchData || !rounds.length) {
    return null;
  }

  const activeRound = rounds[roundIndex] || rounds[0];
  const turns = activeRound?.turns || [];
  const activeTurn = turns[turnIndex] || turns[0];
  if (!activeTurn) {
    return null;
  }

  const orderedPlayerIds = (matchData.players || []).map((player) => player.playerId);
  const metaById = new Map((matchData.players || []).map((player) => [player.playerId, player]));
  const activePlayerId = activeTurn.player.playerId;
  const activePlayerIndex = orderedPlayerIds.indexOf(activePlayerId);
  const distancePositions = ["current", "left", "opposite", "right"];

  const snapshots = [activeTurn.player].concat(activeTurn.opponents || []).map((snapshot) => {
    const playerMeta = metaById.get(snapshot.playerId) || {
      playerId: snapshot.playerId,
      name: snapshot.playerId,
      color: "red",
    };
    const targetIndex = orderedPlayerIds.indexOf(snapshot.playerId);
    const distance =
      targetIndex === -1 ? 0 : (orderedPlayerIds.length + targetIndex - activePlayerIndex) % orderedPlayerIds.length;

    return {
      ...snapshot,
      meta: playerMeta,
      position: distancePositions[distance] || "bench",
      positionLabel: POSITION_LABELS[distancePositions[distance]] || "Bench",
    };
  });

  const currentPlayer = snapshots.find((player) => player.position === "current") || snapshots[0];
  const peripheralPlayers = snapshots
    .filter((player) => player.position !== "current")
    .sort((left, right) => {
      const order = { left: 0, opposite: 1, right: 2 };
      return (order[left.position] ?? 99) - (order[right.position] ?? 99);
    });

  const leaderboard = snapshots
    .slice()
    .sort((left, right) => right.score - left.score)
    .map((player, index) => ({
      place: index + 1,
      playerId: player.playerId,
      name: player.meta.name,
      score: player.score,
      remainingTrains: player.remainingTrains,
      color: PLAYER_COLORS[player.meta.color] || player.meta.color || "#ff8f73",
    }));

  const averageScores = (matchData.averageScores || []).map((record) => {
    const playerMeta = metaById.get(record.playerId) || { name: record.playerId, color: "red" };
    const scoreHistory = record.scores || [];
    const scoreIndex = Math.min(turnIndex, Math.max(scoreHistory.length - 1, 0));
    return {
      playerId: record.playerId,
      name: playerMeta.name,
      color: PLAYER_COLORS[playerMeta.color] || playerMeta.color || "#ff8f73",
      score: scoreHistory.length ? scoreHistory[scoreIndex] : null,
    };
  });

  const routeClaims = [];
  peripheralPlayers.forEach((player) => {
    (player.claimedRoutes || []).forEach((claimedRoute) => {
      const route = normalizeClaimedRoute(claimedRoute);
      routeClaims.push({
        routeId: route.routeId,
        routeLabel: route.routeLabel,
        color: PLAYER_COLORS[player.meta.color] || player.meta.color || "#ff8f73",
      });
    });
  });
  (currentPlayer.claimedRoutes || []).forEach((claimedRoute) => {
    const route = normalizeClaimedRoute(claimedRoute);
    routeClaims.push({
      routeId: route.routeId,
      routeLabel: route.routeLabel,
      color: PLAYER_COLORS[currentPlayer.meta.color] || currentPlayer.meta.color || "#ff8f73",
    });
  });

  const marketCards = (activeTurn.gameObjects?.decks?.marketCards || []).map((cardCode, index) => ({
    id: `market-${index}`,
    code: cardCode,
    imageSrc: resolveTrainCardImage(cardCode),
  }));

  const cardCounts = HAND_ORDER.map((color) => ({
    color,
    label: color === "locomotive" ? "Locomotive" : color.charAt(0).toUpperCase() + color.slice(1),
    count: currentPlayer.hand?.[color] ?? 0,
    imageSrc: CURRENT_PLAYER_CARD_IMAGES[color],
  }));

  const tickets = (currentPlayer.destinationTickets || []).map((ticket, index) => ({
    id: `ticket-${index}`,
    sequence: index + 1,
    from: ticket.from,
    to: ticket.to,
    points: ticket.points,
    completed: Boolean(ticket.completed),
  }));

  const roundOptions = rounds.map((round, index) => ({
    roundIndex: index,
    roundNumber: round.roundNumber,
    turns: (round.turns || []).map((_, turnOptionIndex) => ({
      turnIndex: turnOptionIndex,
      label: `Turn ${turnOptionIndex + 1}`,
    })),
  }));

  return {
    matchName: matchData.name,
    matchStatus: matchData.status,
    currentRoundIndex: roundIndex,
    roundNumber: activeRound.roundNumber,
    turnNumber: turnIndex,
    roundOptions,
    currentPlayer,
    peripheralPlayers,
    leaderboard,
    averageScores,
    routeClaims,
    marketCards,
    cardCounts,
    tickets,
  };
}

function deriveTopBarStatus(matchData, roundIndex, turnIndex) {
  if (!matchData) {
    return {
      roundNumber: 0,
      turnNumber: 0,
      activePlayerName: "Standby",
    };
  }

  const model = buildReplayModel(matchData, roundIndex, turnIndex);
  if (!model) {
    return {
      roundNumber: 0,
      turnNumber: 0,
      activePlayerName: "Standby",
    };
  }

  return {
    roundNumber: model.roundNumber,
    turnNumber: model.turnNumber,
    activePlayerName: model.currentPlayer.meta.name,
  };
}

export {
  buildReplayModel,
  deriveTopBarStatus,
};
