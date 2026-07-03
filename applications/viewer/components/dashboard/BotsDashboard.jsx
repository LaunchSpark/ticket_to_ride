import { RUN_TRANSITION, h, useDeferredValue, useEffect, useMemo, useState } from "../runtime.jsx";
import { CardShell } from "../atoms/CardShell.jsx";
import { UiIcon } from "../atoms/UiIcon.jsx";
import { launchNotebook, listBots, registerBot } from "../services/bot-registry.jsx";

const DEFAULT_TEST_BOT_ID = "random_bot";

function formatBotTimestamp(value) {
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

function buildBotSourceLabel(bot) {
  return `${bot.sourceBaseUrl}${bot.discoveryPath}`;
}

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
  const sourceLabel = buildBotSourceLabel(bot);
  return {
    ...bot,
    createdLabel: formatBotTimestamp(bot.createdAt),
    searchText: [bot.botId, bot.name, bot.version, sourceLabel, bot.sourceKind].join(" ").toLowerCase(),
    sourceLabel,
  };
}

function AddBotModal(props) {
  const [botId, setBotId] = useState("");
  const [submitState, setSubmitState] = useState({ kind: "idle", message: "" });

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape" && submitState.kind !== "saving") {
        props.onClose();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [props.onClose, submitState.kind]);

  async function handleSubmit(event) {
    event.preventDefault();

    const normalizedBotId = botId.trim();
    if (!normalizedBotId) {
      setSubmitState({ kind: "error", message: "Bot ID is required." });
      return;
    }

    try {
      setSubmitState({ kind: "saving", message: "" });
      const bot = await registerBot(props.apiBase, normalizedBotId);
      RUN_TRANSITION(() => {
        props.onRegistered(bot);
        props.onClose();
      });
    } catch (error) {
      setSubmitState({
        kind: "error",
        message: error.message || "Unable to register the requested bot.",
      });
    }
  }

  return h(
    "div",
    {
      className: "bots-add-modal-backdrop",
      onClick: submitState.kind === "saving" ? undefined : props.onClose,
    },
    h(
      "div",
      {
        className: "bots-add-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": "Register bot",
      },
      h(
        "div",
        { className: "bots-add-modal-header" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Bot Registry"),
          h("h2", { className: "panel-title" }, "Add Bot"),
          h(
            "p",
            { className: "bots-panel-subtitle" },
            `Register a locally discoverable bot by ID. Built-in test bot ID: ${DEFAULT_TEST_BOT_ID}.`
          )
        ),
        h(
          "button",
          {
            className: "matches-modal-close",
            type: "button",
            onClick: props.onClose,
            disabled: submitState.kind === "saving",
            "aria-label": "Close add bot modal",
          },
          h(UiIcon, { name: "close" })
        )
      ),
      h(
        "form",
        { className: "bots-add-form", onSubmit: handleSubmit },
        h(
          "label",
          { className: "matches-modal-field" },
          h("span", null, "Bot ID"),
          h("input", {
            type: "text",
            value: botId,
            placeholder: DEFAULT_TEST_BOT_ID,
            autoFocus: true,
            disabled: submitState.kind === "saving",
            onInput: (event) => setBotId(event.target.value),
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
              onClick: props.onClose,
              disabled: submitState.kind === "saving",
            },
            "Cancel"
          ),
          h(
            "button",
            {
              className: "matches-modal-link bots-panel-add",
              type: "submit",
              disabled: submitState.kind === "saving",
            },
            submitState.kind === "saving" ? "Registering..." : "Register Bot"
          )
        )
      )
    )
  );
}

function BotsDashboard(props) {
  const [bots, setBots] = useState([]);
  const [query, setQuery] = useState("");
  const [fetchState, setFetchState] = useState({ kind: "loading", message: "" });
  const [isAddBotOpen, setAddBotOpen] = useState(false);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isCancelled = false;

    async function loadRegisteredBots() {
      try {
        setFetchState({ kind: "loading", message: "" });
        const payload = await listBots(props.apiBase);
        if (isCancelled) {
          return;
        }

        setBots(Array.isArray(payload) ? sortBots(payload) : []);
        setFetchState({ kind: "ready", message: "" });
      } catch (error) {
        if (!isCancelled) {
          setFetchState({
            kind: "error",
            message: error.message || "Unable to load registered bots.",
          });
        }
      }
    }

    loadRegisteredBots();
    return () => {
      isCancelled = true;
    };
  }, [props.apiBase]);

  const normalizedBots = useMemo(() => sortBots(bots).map(normalizeBot), [bots]);
  const filteredBots = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return normalizedBots;
    }

    return normalizedBots.filter((bot) => bot.searchText.includes(normalizedQuery));
  }, [deferredQuery, normalizedBots]);

  function handleRegisteredBot(bot) {
    setBots((currentBots) => {
      const nextBots = currentBots.filter((candidate) => candidate.botId !== bot.botId).concat(bot);
      return sortBots(nextBots);
    });
    setFetchState({ kind: "ready", message: "" });
  }

  const [launchState, setLaunchState] = useState({});

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
            h("p", { className: "shell-eyebrow" }, "Bot Registry"),
            h("h2", { className: "panel-title" }, "Registered Bots"),
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
              placeholder: "Search by bot ID, name, or source",
              onInput: (event) => setQuery(event.target.value),
            })
          )
        ),
        h(
          "p",
          { className: "bots-summary" },
          fetchState.kind === "loading"
            ? "Loading registered bots..."
            : fetchState.kind === "error"
              ? fetchState.message
              : `${filteredBots.length} of ${normalizedBots.length} bots shown`
        ),
        h(
          "div",
          { className: "bots-list" },
          fetchState.kind === "loading"
            ? h("div", { className: "bots-empty" }, "Checking the local bot registry.")
            : fetchState.kind === "error"
              ? h("div", { className: "bots-empty" }, fetchState.message)
              : !normalizedBots.length
                ? h(
                    "div",
                    { className: "bots-empty" },
                    `No bots are registered yet. Try adding the built-in ${DEFAULT_TEST_BOT_ID}.`
                  )
                : !filteredBots.length
                  ? h("div", { className: "bots-empty" }, "No registered bots match the current search.")
                  : filteredBots.map((bot) =>
                      h(
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
                          h("span", { className: "matches-modal-status" }, "Local API")
                        ),
                        h(
                          "div",
                          { className: "matches-modal-card-meta" },
                          h("span", { className: "matches-modal-meta-pill" }, bot.botId),
                          h("span", { className: "matches-modal-meta-pill" }, bot.version),
                          h("span", { className: "matches-modal-meta-pill" }, bot.sourceKind),
                          bot.createdLabel
                            ? h("span", { className: "matches-modal-meta-pill" }, `Registered ${bot.createdLabel}`)
                            : null
                        ),
                        h(
                          "div",
                          { className: "bots-card-actions" },
                          h(
                            "button",
                            {
                              className: "matches-modal-link",
                              type: "button",
                              disabled: launchState[bot.botId] === "opening",
                              onClick: () => handleOpenNotebook(bot),
                            },
                            launchState[bot.botId] === "opening" ? "Opening..." : "Open Notebook"
                          ),
                          launchState[bot.botId] === "error"
                            ? h("span", { className: "bots-add-error" }, "Unable to open the notebook.")
                            : null
                        )
                      )
                    )
        )
      )
    ),
    h("section", { className: "bots-grid-slot-empty-top" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    h("section", { className: "bots-grid-slot-empty-bottom" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    isAddBotOpen
      ? h(AddBotModal, {
          apiBase: props.apiBase,
          onClose: () => setAddBotOpen(false),
          onRegistered: handleRegisteredBot,
        })
      : null
  );
}

export { BotsDashboard };
