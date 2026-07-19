import { Fragment, h, useDeferredValue, useEffect, useMemo, useState } from "../runtime.jsx";
import { buildBackendUrl, buildPocketBaseUrl } from "../services/url-utils.jsx";
import { ShellNavItem } from "../atoms/ShellNavItem.jsx";
import { UiIcon } from "../atoms/UiIcon.jsx";

function formatMatchTimestamp(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function toMatchText(value, fallback = "") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return String(value);
}

function collectPlayerNames(match) {
  if (Array.isArray(match?.players)) {
    return match.players
      .map((player) => player?.name || player?.meta?.name || player?.playerId)
      .filter(Boolean)
      .map((player) => String(player));
  }

  if (Array.isArray(match?.playerNames)) {
    return match.playerNames.filter(Boolean).map((player) => String(player));
  }

  return [];
}

function normalizeMatch(match, index) {
  const matchId = toMatchText(match?.matchId || match?.id, `match-${index + 1}`);
  const name = toMatchText(match?.name || match?.matchName || match?.title, matchId);
  const statusLabel = toMatchText(match?.status || match?.state, "Unknown");
  const statusKey = statusLabel.toLowerCase();
  const playerNames = collectPlayerNames(match);
  const playerCount = match?.playerCount || playerNames.length || null;
  const roundsCount = match?.roundCount || (Array.isArray(match?.rounds) ? match.rounds.length : null);
  const updatedLabel = formatMatchTimestamp(match?.updatedAt || match?.modifiedAt || match?.lastUpdatedAt);
  const createdLabel = formatMatchTimestamp(match?.createdAt || match?.startedAt || match?.created);
  const searchText = [
    matchId,
    name,
    statusLabel,
    playerNames.join(" "),
    playerCount ? `${playerCount}` : "",
    roundsCount ? `${roundsCount}` : "",
    createdLabel || "",
    updatedLabel || "",
  ]
    .join(" ")
    .toLowerCase();

  return {
    matchId,
    name,
    statusKey,
    statusLabel,
    playerNames,
    playerCount,
    roundsCount,
    createdLabel,
    updatedLabel,
    searchText,
  };
}

function MatchBrowserModal(props) {
  const [matches, setMatches] = useState([]);
  const [query, setQuery] = useState("");
  const [playerCountFilter, setPlayerCountFilter] = useState("");
  const [fetchState, setFetchState] = useState({ kind: "loading", message: "" });
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isCancelled = false;

    async function loadMatches() {
      try {
        setFetchState({ kind: "loading", message: "" });

        const response = await fetch(`${props.apiBase}/matches`);
        if (!response.ok) {
          throw new Error(`Match list request failed with status ${response.status}`);
        }

        const payload = await response.json();
        if (isCancelled) {
          return;
        }

        setMatches(Array.isArray(payload) ? payload : []);
        setFetchState({ kind: "ready", message: "" });
      } catch (error) {
        if (!isCancelled) {
          setFetchState({ kind: "error", message: error.message || "Unable to load matches." });
        }
      }
    }

    loadMatches();
    return () => {
      isCancelled = true;
    };
  }, [props.apiBase]);

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape") {
        props.onClose();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [props.onClose]);

  const normalizedMatches = useMemo(() => matches.map(normalizeMatch), [matches]);
  const filteredMatches = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    const normalizedPlayerCount =
      playerCountFilter === "" ? null : Number.parseInt(playerCountFilter, 10);

    return normalizedMatches.filter((match) => {
      const matchesQuery = !normalizedQuery || match.searchText.includes(normalizedQuery);
      const matchesPlayerCount =
        normalizedPlayerCount === null ||
        (!Number.isNaN(normalizedPlayerCount) && match.playerCount === normalizedPlayerCount);
      return matchesQuery && matchesPlayerCount;
    });
  }, [deferredQuery, normalizedMatches, playerCountFilter]);

  function handleLoadMatch(matchId) {
    props.onLoadMatch(matchId);
    props.onClose();
  }

  return h(
    "div",
    { className: "matches-modal-backdrop", onClick: props.onClose },
    h(
      "div",
      {
        className: "matches-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": "Match browser",
      },
      h(
        "div",
        { className: "matches-modal-header" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Match Browser"),
          h("h2", { className: "panel-title" }, "Browse Stored Matches"),
          h("p", { className: "matches-modal-subtitle" }, props.apiBase)
        ),
        h(
          "div",
          { className: "matches-modal-actions" },
          h(
            "a",
            {
              className: "matches-modal-link",
              href: buildBackendUrl(props.apiBase),
              target: "_blank",
              rel: "noreferrer",
              title: "Open backend in a new tab",
            },
            h(UiIcon, { name: "open_in_new" }),
            h("span", null, "Open API")
          ),
          h(
            "button",
            {
              className: "matches-modal-close",
              type: "button",
              onClick: props.onClose,
              "aria-label": "Close match browser",
            },
            h(UiIcon, { name: "close" })
          )
        )
      ),
      h(
        "div",
        { className: "matches-modal-toolbar" },
        h(
          "label",
          { className: "matches-modal-field" },
          h("span", null, "Search"),
          h("input", {
            type: "search",
            value: query,
            placeholder: "Search by match, player, or status",
            onInput: (event) => setQuery(event.target.value),
            autoFocus: true,
          })
        ),
        h(
          "label",
          { className: "matches-modal-field matches-modal-field--compact" },
          h("span", null, "Players"),
          h("input", {
            type: "number",
            inputMode: "numeric",
            min: "1",
            step: "1",
            value: playerCountFilter,
            placeholder: "Any",
            onInput: (event) => setPlayerCountFilter(event.target.value),
            "aria-label": "Filter matches by number of players",
          })
        ),
        h(
          "button",
          {
            className: "matches-modal-reset",
            type: "button",
            onClick: () => {
              setQuery("");
              setPlayerCountFilter("");
            },
          },
          "Reset"
        )
      ),
      h(
        "p",
        { className: "matches-modal-summary" },
        fetchState.kind === "loading"
          ? "Loading matches..."
          : fetchState.kind === "error"
            ? fetchState.message
            : `${filteredMatches.length} of ${normalizedMatches.length} matches shown`
      ),
      h(
        "div",
        { className: "matches-modal-results" },
        fetchState.kind === "loading"
          ? h("div", { className: "matches-modal-empty" }, "Loading stored matches from the backend.")
          : fetchState.kind === "error"
            ? h("div", { className: "matches-modal-empty" }, fetchState.message)
            : !normalizedMatches.length
              ? h("div", { className: "matches-modal-empty" }, "No matches are stored yet.")
              : !filteredMatches.length
                ? h("div", { className: "matches-modal-empty" }, "No matches match the current search and filters.")
                : filteredMatches.map((match) =>
                    h(
                      "article",
                      {
                        key: match.matchId,
                        className: props.activeMatchId === match.matchId ? "matches-modal-card is-current" : "matches-modal-card",
                      },
                      h(
                        "div",
                        { className: "matches-modal-card-top" },
                        h(
                          "div",
                          { className: "matches-modal-card-copy" },
                          h("h3", null, match.name),
                          h("p", null, match.matchId)
                        ),
                        h(
                          "span",
                          { className: "matches-modal-status" },
                          match.statusLabel
                        )
                      ),
                      h(
                        "div",
                        { className: "matches-modal-card-meta" },
                        match.playerCount
                          ? h("span", { className: "matches-modal-meta-pill" }, `${match.playerCount} players`)
                          : null,
                        match.roundsCount
                          ? h("span", { className: "matches-modal-meta-pill" }, `${match.roundsCount} rounds`)
                          : null,
                        match.createdLabel
                          ? h("span", { className: "matches-modal-meta-pill" }, `Created ${match.createdLabel}`)
                          : null,
                        match.updatedLabel
                          ? h("span", { className: "matches-modal-meta-pill" }, `Updated ${match.updatedLabel}`)
                          : null
                      ),
                      h(
                        "div",
                        { className: "matches-modal-card-footer" },
                        h(
                          "p",
                          { className: "matches-modal-players" },
                          match.playerNames.length ? match.playerNames.join(", ") : "Player roster unavailable"
                        ),
                        props.activeMatchId === match.matchId
                          ? h("span", { className: "matches-modal-coming-soon" }, "Loaded")
                          : h(
                              "button",
                              {
                                className: "matches-modal-load-button",
                                type: "button",
                                onClick: () => handleLoadMatch(match.matchId),
                              },
                              "Load Match"
                            )
                      )
                    )
                  )
      )
    )
  );
}

function NavBar(props) {
  const [isMatchBrowserOpen, setMatchBrowserOpen] = useState(false);

  return h(
    Fragment,
    null,
    h(
      "aside",
      { className: props.isOpen ? "shell-nav-bar is-open" : "shell-nav-bar" },
      h(
        "div",
        { className: "shell-nav-bar-inner" },
        h(
          "div",
          { className: "shell-brand" },
          h("div", { className: "shell-brand-mark", "aria-hidden": "true" }, "TTR"),
          h(
            "div",
            { className: "shell-brand-copy" },
            h("p", { className: "shell-eyebrow" }, "Arena"),
            h("h2", { className: "shell-brand-title" }, "Engine Tournament"),
          )
        ),
        h(
          "div",
          { className: "shell-nav-bar-section" },
          h("p", { className: "shell-section-label" }, "Workspace"),
          h(ShellNavItem, {
            active: props.currentPath === "/",
            icon: "leaderboard",
            label: "Match Replay",
            description: props.activePlayerName ? `Tracking ${props.activePlayerName}` : "Live replay surface",
            href: props.replayHref,
            title: "Open match replay",
          }),
          h(ShellNavItem, {
            active: props.currentPath === "/bots",
            icon: "smart_toy",
            label: "Bots",
            description: "Discover local bots and connections",
            href: props.botsHref,
            title: "Open bot workspace",
          }),
          h(ShellNavItem, {
            icon: "query_stats",
            label: "Matches",
            description: "Browse and filter stored replays",
            onClick: () => setMatchBrowserOpen(true),
            title: "Browse matches",
          }),
          h(ShellNavItem, {
            icon: "inventory_2",
            label: "PocketBase",
            description: "Storage console",
            href: buildPocketBaseUrl(props.apiBase),
            external: true,
            title: "Open PocketBase admin UI",
          })
        )
      )
    ),
    isMatchBrowserOpen
      ? h(MatchBrowserModal, {
          apiBase: props.apiBase,
          activeMatchId: props.activeMatchId,
          onLoadMatch: props.onLoadMatch,
          onClose: () => setMatchBrowserOpen(false),
        })
      : null
  );
}

export { NavBar };
