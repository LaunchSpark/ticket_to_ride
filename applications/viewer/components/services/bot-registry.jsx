async function readResponseError(response, fallbackMessage) {
  try {
    const payload = await response.json();
    if (payload?.detail) {
      throw new Error(payload.detail);
    }
  } catch (error) {
    if (error instanceof Error && error.message !== "Unexpected end of JSON input") {
      throw error;
    }
  }

  throw new Error(fallbackMessage);
}

async function listBots(apiBase) {
  const response = await fetch(`${apiBase}/bots`);
  if (!response.ok) {
    return readResponseError(response, `Bot list request failed with status ${response.status}`);
  }

  return response.json();
}

async function registerBot(apiBase, botId) {
  const response = await fetch(`${apiBase}/bots`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ botId }),
  });

  if (!response.ok) {
    return readResponseError(response, `Bot registration failed with status ${response.status}`);
  }

  return response.json();
}

async function launchNotebook(apiBase, botId) {
  const response = await fetch(`${apiBase}/notebooks/${encodeURIComponent(botId)}/launch`, {
    method: "POST",
  });

  if (!response.ok) {
    return readResponseError(response, `Notebook launch failed with status ${response.status}`);
  }

  return response.json();
}

export {
  launchNotebook,
  listBots,
  registerBot,
};
