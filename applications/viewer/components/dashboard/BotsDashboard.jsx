import { RUN_TRANSITION, h, useDeferredValue, useEffect, useMemo, useState } from "../runtime.jsx";
import { CardShell } from "../atoms/CardShell.jsx";
import { UiIcon } from "../atoms/UiIcon.jsx";
import { addConnection, createBot, launchNotebook, listBots, removeConnection } from "../services/bot-registry.jsx";

function sortBots(bots) {
  return bots
    .slice()
    .sort((left, right) => {
      const nameComparison = left.name.localeCompare(right.name, undefined, { sensitivity: "base" });
      if (nameComparison !== 0) {
        return nameComparison;
      }

      return left.botId.localeCompare(right.botId, undefined, { sensitivity: "base" });
    });
}

function normalizeBot(bot) {
  const sourceLabel = bot.source === "local" ? "Local" : bot.baseUrl || "Remote";
  return {
    ...bot,
    searchText: [bot.botId, bot.name, bot.version, (bot.tags || []).join(" "), bot.source, sourceLabel]
      .join(" ")
      .toLowerCase(),
    sourceLabel,
  };
}

function AddBotModal(props) {
  const [mode, setMode] = useState("choose");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [submitState, setSubmitState] = useState({ kind: "idle", message: "" });
  const isSaving = submitState.kind === "saving";

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape" && !isSaving) {
        props.onClose();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [props.onClose, isSaving]);

  async function handleCreate(event) {
    event.preventDefault();

    const trimmedName = name.trim();
    if (!trimmedName) {
      setSubmitState({ kind: "error", message: "Bot name is required." });
      return;
    }

    try {
      setSubmitState({ kind: "saving", message: "" });
      const result = await createBot(props.apiBase, trimmedName);
      window.open(result.url, "_blank", "noopener");
      RUN_TRANSITION(() => {
        props.onChanged();
        props.onClose();
      });
    } catch (error) {
      setSubmitState({
        kind: "error",
        message: error.message || "Unable to create the bot.",
      });
    }
  }

  async function handleConnect(event) {
    event.preventDefault();

    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setSubmitState({ kind: "error", message: "Connection URL is required." });
      return;
    }

    try {
      setSubmitState({ kind: "saving", message: "" });
      await addConnection(props.apiBase, trimmedUrl);
      RUN_TRANSITION(() => {
        props.onChanged();
        props.onClose();
      });
    } catch (error) {
      setSubmitState({
        kind: "error",
        message: error.message || "Unable to connect to the bot API.",
      });
    }
  }

  function switchMode(nextMode) {
    setSubmitState({ kind: "idle", message: "" });
    setMode(nextMode);
  }

  const title = mode === "new" ? "New Bot" : mode === "connect" ? "Add Connection" : "Add Bot";
  const subtitle =
    mode === "new"
      ? "Name your bot; a notebook is scaffolded from the template and opened for editing."
      : mode === "connect"
        ? "Point at someone else's bot API base URL, e.g. http://friend-host:8001."
        : "Create a brand-new bot or connect to bots served from another machine.";

  return h(
    "div",
    {
      className: "bots-add-modal-backdrop",
      onClick: isSaving ? undefined : props.onClose,
    },
    h(
      "div",
      {
        className: "bots-add-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": title,
      },
      h(
        "div",
        { className: "bots-add-modal-header" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Bot Directory"),
          h("h2", { className: "panel-title" }, title),
          h("p", { className: "bots-panel-subtitle" }, subtitle)
        ),
        h(
          "button",
          {
            className: "matches-modal-close",
            type: "button",
            onClick: props.onClose,
            disabled: isSaving,
            "aria-label": "Close add bot modal",
          },
          h(UiIcon, { name: "close" })
        )
      ),
      mode === "choose"
        ? h(
            "div",
            { className: "bots-add-choice-grid" },
            h(
              "button",
              { className: "bots-add-choice", type: "button", onClick: () => switchMode("new") },
              h(UiIcon, { name: "add" }),
              h("span", { className: "bots-add-choice-title" }, "New Bot"),
              h("span", { className: "bots-add-choice-copy" }, "Scaffold a notebook bot from a name.")
            ),
            h(
              "button",
              { className: "bots-add-choice", type: "button", onClick: () => switchMode("connect") },
              h(UiIcon, { name: "link" }),
              h("span", { className: "bots-add-choice-title" }, "Add Connection"),
              h("span", { className: "bots-add-choice-copy" }, "Connect to someone else's bot API by URL.")
            )
          )
        : h(
            "form",
            { className: "bots-add-form", onSubmit: mode === "new" ? handleCreate : handleConnect },
            mode === "new"
              ? h(
                  "label",
                  { className: "matches-modal-field" },
                  h("span", null, "Bot name"),
                  h("input", {
                    type: "text",
                    value: name,
                    placeholder: "My Cool Bot",
                    autoFocus: true,
                    disabled: isSaving,
                    onInput: (event) => setName(event.target.value),
                  })
                )
              : h(
                  "label",
                  { className: "matches-modal-field" },
                  h("span", null, "Bot API URL"),
                  h("input", {
                    type: "url",
                    value: url,
                    placeholder: "http://friend-host:8001",
                    autoFocus: true,
                    disabled: isSaving,
                    onInput: (event) => setUrl(event.target.value),
                  })
                ),
            submitState.kind === "error"
              ? h("p", { className: "bots-add-error" }, submitState.message)
              : null,
            h(
              "div",
              { className: "bots-add-modal-actions" },
              h(
                "button",
                {
                  className: "matches-modal-reset",
                  type: "button",
                  onClick: () => switchMode("choose"),
                  disabled: isSaving,
                },
                "Back"
              ),
              h(
                "button",
                {
                  className: "matches-modal-link bots-panel-add",
                  type: "submit",
                  disabled: isSaving,
                },
                isSaving
                  ? mode === "new"
                    ? "Creating..."
                    : "Connecting..."
                  : mode === "new"
                    ? "Create Bot"
                    : "Connect"
              )
            )
          )
    )
  );
}

function BotCard(props) {
  const bot = props.bot;
  return h(
    "article",
    { key: bot.botId, className: "bots-card" },
    h(
      "div",
      { className: "bots-card-top" },
      h(
        "div",
        { className: "bots-card-copy" },
        h("h3", null, bot.name),
        h("p", { className: "bots-card-path" }, bot.sourceLabel)
      ),
      h(
        "span",
        { className: "matches-modal-status" },
        bot.source === "local" ? "Local" : "Remote"
      )
    ),
    h(
      "div",
      { className: "matches-modal-card-meta" },
      h("span", { className: "matches-modal-meta-pill" }, bot.botId),
      h("span", { className: "matches-modal-meta-pill" }, bot.version),
      (bot.tags || []).map((tag) => h("span", { key: tag, className: "matches-modal-meta-pill" }, tag))
    ),
    bot.source === "local"
      ? h(
          "div",
          { className: "bots-card-actions" },
          h(
            "button",
            {
              className: "matches-modal-link",
              type: "button",
              disabled: props.launchState === "opening",
              onClick: () => props.onOpenNotebook(bot),
            },
            props.launchState === "opening" ? "Opening..." : "Open Notebook"
          ),
          props.launchState === "error"
            ? h("span", { className: "bots-add-error" }, "Unable to open the notebook.")
            : null
        )
      : null
  );
}

function BotsDashboard(props) {
  const [directory, setDirectory] = useState({ bots: [], connections: [] });
  const [query, setQuery] = useState("");
  const [fetchState, setFetchState] = useState({ kind: "loading", message: "" });
  const [isAddBotOpen, setAddBotOpen] = useState(false);
  const [launchState, setLaunchState] = useState({});
  const [pendingRemoveId, setPendingRemoveId] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isCancelled = false;

    async function loadDirectory() {
      try {
        setFetchState({ kind: "loading", message: "" });
        const payload = await listBots(props.apiBase);
        if (isCancelled) {
          return;
        }

        setDirectory({
          bots: Array.isArray(payload?.bots) ? payload.bots : [],
          connections: Array.isArray(payload?.connections) ? payload.connections : [],
        });
        setFetchState({ kind: "ready", message: "" });
      } catch (error) {
        if (!isCancelled) {
          setFetchState({
            kind: "error",
            message: error.message || "Unable to load the bot directory.",
          });
        }
      }
    }

    loadDirectory();
    return () => {
      isCancelled = true;
    };
  }, [props.apiBase, reloadToken]);

  function refresh() {
    setReloadToken((token) => token + 1);
  }

  const normalizedBots = useMemo(() => sortBots(directory.bots).map(normalizeBot), [directory.bots]);
  const filteredBots = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return normalizedBots;
    }

    return normalizedBots.filter((bot) => bot.searchText.includes(normalizedQuery));
  }, [deferredQuery, normalizedBots]);

  const localBots = filteredBots.filter((bot) => bot.source === "local");

  async function handleOpenNotebook(bot) {
    setLaunchState((current) => ({ ...current, [bot.botId]: "opening" }));
    try {
      const result = await launchNotebook(props.apiBase, bot.botId);
      window.open(result.url, "_blank", "noopener");
      setLaunchState((current) => ({ ...current, [bot.botId]: "idle" }));
    } catch (error) {
      setLaunchState((current) => ({ ...current, [bot.botId]: "error" }));
    }
  }

  async function handleRemoveConnection(connection) {
    if (pendingRemoveId !== connection.connectionId) {
      setPendingRemoveId(connection.connectionId);
      return;
    }

    try {
      await removeConnection(props.apiBase, connection.connectionId);
      setPendingRemoveId(null);
      refresh();
    } catch (error) {
      setPendingRemoveId(null);
      setFetchState({ kind: "error", message: error.message || "Unable to remove the connection." });
    }
  }

  function renderConnectionGroup(connection) {
    const connectionBots = filteredBots.filter((bot) => bot.connectionId === connection.connectionId);
    return h(
      "div",
      { key: connection.connectionId, className: "bots-group" },
      h(
        "div",
        { className: "bots-group-header" },
        h(
          "div",
          { className: "bots-group-title" },
          h("h3", null, connection.url),
          h(
            "span",
            {
              className:
                connection.status === "online"
                  ? "bots-status-pill"
                  : "bots-status-pill bots-status-pill--offline",
            },
            connection.status === "online" ? "Online" : "Offline"
          )
        ),
        h(
          "button",
          {
            className: "matches-modal-reset bots-connection-remove",
            type: "button",
            onClick: () => handleRemoveConnection(connection),
          },
          pendingRemoveId === connection.connectionId ? "Confirm remove" : "Remove"
        )
      ),
      connection.status === "offline"
        ? h("div", { className: "bots-empty" }, connection.error || "This connection is unreachable.")
        : !connectionBots.length
          ? h("div", { className: "bots-empty" }, "No bots match on this connection.")
          : connectionBots.map((bot) =>
              h(BotCard, {
                key: bot.botId,
                bot,
                launchState: launchState[bot.botId],
                onOpenNotebook: handleOpenNotebook,
              })
            )
    );
  }

  return h(
    "div",
    { className: "bots-dashboard-grid" },
    h(
      "section",
      { className: "bots-grid-slot-list" },
      h(
        CardShell,
        { className: "bots-panel bots-panel--registry" },
        h(
          "div",
          { className: "panel-header bots-panel-header" },
          h(
            "div",
            null,
            h("p", { className: "shell-eyebrow" }, "Bot Directory"),
            h("h2", { className: "panel-title" }, "Bots"),
            h("p", { className: "bots-panel-subtitle" }, props.apiBase)
          ),
          h(
            "button",
            {
              className: "matches-modal-link bots-panel-add",
              type: "button",
              onClick: () => setAddBotOpen(true),
            },
            h(UiIcon, { name: "add" }),
            h("span", null, "Add Bot")
          )
        ),
        h(
          "div",
          { className: "bots-toolbar" },
          h(
            "label",
            { className: "matches-modal-field bots-toolbar-search" },
            h("span", null, "Search"),
            h("input", {
              type: "search",
              value: query,
              placeholder: "Search by bot ID, name, tag, or source",
              onInput: (event) => setQuery(event.target.value),
            })
          )
        ),
        h(
          "p",
          { className: "bots-summary" },
          fetchState.kind === "loading"
            ? "Discovering bots..."
            : fetchState.kind === "error"
              ? fetchState.message
              : `${filteredBots.length} of ${normalizedBots.length} bots shown`
        ),
        h(
          "div",
          { className: "bots-list" },
          fetchState.kind === "loading"
            ? h("div", { className: "bots-empty" }, "Scanning local bots and connections.")
            : fetchState.kind === "error"
              ? h("div", { className: "bots-empty" }, fetchState.message)
              : [
                  h(
                    "div",
                    { key: "local", className: "bots-group" },
                    h(
                      "div",
                      { className: "bots-group-header" },
                      h(
                        "div",
                        { className: "bots-group-title" },
                        h("h3", null, "Local Bots"),
                        h("span", { className: "bots-status-pill" }, String(localBots.length))
                      )
                    ),
                    !localBots.length
                      ? h(
                          "div",
                          { className: "bots-empty" },
                          "No local bots discovered. Create one with Add Bot, or drop a notebook into integrations/external/bots/."
                        )
                      : localBots.map((bot) =>
                          h(BotCard, {
                            key: bot.botId,
                            bot,
                            launchState: launchState[bot.botId],
                            onOpenNotebook: handleOpenNotebook,
                          })
                        )
                  ),
                  directory.connections.map(renderConnectionGroup),
                ]
        )
      )
    ),
    h("section", { className: "bots-grid-slot-empty-top" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    h("section", { className: "bots-grid-slot-empty-bottom" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    isAddBotOpen
      ? h(AddBotModal, {
          apiBase: props.apiBase,
          onClose: () => setAddBotOpen(false),
          onChanged: refresh,
        })
      : null
  );
}

export { BotsDashboard };
