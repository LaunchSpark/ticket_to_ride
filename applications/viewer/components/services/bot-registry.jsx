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

async function createBot(apiBase, name) {
  const response = await fetch(`${apiBase}/bots/new`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name }),
  });

  if (!response.ok) {
    return readResponseError(response, `Bot creation failed with status ${response.status}`);
  }

  return response.json();
}

async function addConnection(apiBase, url) {
  const response = await fetch(`${apiBase}/bot-connections`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    return readResponseError(response, `Connection request failed with status ${response.status}`);
  }

  return response.json();
}

async function removeConnection(apiBase, connectionId) {
  const response = await fetch(`${apiBase}/bot-connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    return readResponseError(response, `Connection removal failed with status ${response.status}`);
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
  addConnection,
  createBot,
  launchNotebook,
  listBots,
  removeConnection,
};
