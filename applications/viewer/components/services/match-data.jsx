import { buildStatusState } from "./url-utils.jsx";

async function loadMatchPayload(apiBase, initialMatchId) {
  let activeMatchId = initialMatchId;

  if (!activeMatchId) {
    const matchListResponse = await fetch(`${apiBase}/matches`);
    if (!matchListResponse.ok) {
      throw new Error(`Match list request failed with status ${matchListResponse.status}`);
    }

    const matches = await matchListResponse.json();
    if (!matches.length) {
      return {
        status: buildStatusState(
          "empty",
          "No Matches Yet",
          "No matches are stored yet. Start a game or create a match in the control plane, then reload this page."
        ),
        matchData: null,
        matchId: null,
      };
    }

    activeMatchId = matches[0].matchId;
  }

  const matchResponse = await fetch(`${apiBase}/matches/${activeMatchId}`);
  if (!matchResponse.ok) {
    throw new Error(`Match request failed with status ${matchResponse.status}`);
  }

  return {
    status: null,
    matchData: await matchResponse.json(),
    matchId: activeMatchId,
  };
}

export { loadMatchPayload };
