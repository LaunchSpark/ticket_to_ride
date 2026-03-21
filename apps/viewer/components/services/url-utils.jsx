function readParams() {
  const query = new URLSearchParams(window.location.search);
  const apiBase = (query.get("api_base") || "http://127.0.0.1:8000").replace(/\/$/, "");
  const matchId = query.get("match_id");
  return { apiBase, matchId };
}

function buildBackendUrl(apiBase) {
  return apiBase.endsWith("/") ? apiBase : `${apiBase}/`;
}

function buildPocketBaseUrl(apiBase) {
  try {
    const parsed = new URL(apiBase);
    return `${parsed.origin.replace(":8000", ":8090")}/_/`;
  } catch (error) {
    return "http://127.0.0.1:8090/_/";
  }
}

function buildStatusState(kind, title, message) {
  return { kind, title, message };
}

export {
  buildBackendUrl,
  buildPocketBaseUrl,
  buildStatusState,
  readParams,
};
