function buildPlaybackPointers(rounds) {
  const pointers = [];
  rounds.forEach((round, roundIndex) => {
    round.turns.forEach((_, turnIndex) => {
      pointers.push({ roundIndex, turnIndex });
    });
  });
  return pointers;
}

function findPlaybackIndex(pointers, roundIndex, turnIndex) {
  return pointers.findIndex((pointer) => pointer.roundIndex === roundIndex && pointer.turnIndex === turnIndex);
}

function movePlaybackCursor(matchData, roundIndex, turnIndex, delta) {
  if (!matchData) {
    return { roundIndex: 0, turnIndex: 0, changed: false };
  }

  const pointers = buildPlaybackPointers(matchData.rounds || []);
  if (!pointers.length) {
    return { roundIndex: 0, turnIndex: 0, changed: false };
  }

  const currentIndex = Math.max(0, findPlaybackIndex(pointers, roundIndex, turnIndex));
  const nextIndex = Math.min(Math.max(currentIndex + delta, 0), pointers.length - 1);
  const nextPointer = pointers[nextIndex];

  return {
    roundIndex: nextPointer.roundIndex,
    turnIndex: nextPointer.turnIndex,
    changed: nextIndex !== currentIndex,
  };
}

export {
  buildPlaybackPointers,
  findPlaybackIndex,
  movePlaybackCursor,
};
