import { Fragment, h, useEffect, useState } from "../../runtime.jsx";
import { CardShell } from "../../atoms/CardShell.jsx";
import { MetricRowCard } from "./MetricRowCard.jsx";
import { PlaybackButton } from "./PlaybackButton.jsx";
import { ScannerRowCard } from "./ScannerRowCard.jsx";
import { UiIcon } from "../../atoms/UiIcon.jsx";

function JumpToTurnModal(props) {
  if (!props.isOpen) {
    return null;
  }

  const roundOptions = props.roundOptions || [];
  const activeRound = roundOptions[props.roundIndex] || roundOptions[0] || { turns: [] };
  const maxRoundNumber = Math.max(roundOptions.length, 1);
  const maxTurnNumber = Math.max((activeRound.turns || []).length, 1);

  return h(
    "div",
    { className: "jump-turn-modal-backdrop", onClick: props.onClose },
    h(
      "div",
      {
        className: "jump-turn-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": "Jump to round and turn",
      },
      h(
        "div",
        { className: "panel-header panel-header-tight" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Playback Jump"),
          h("h2", { className: "panel-title" }, "Go To Turn")
        ),
        h(
          "button",
          {
            className: "player-stats-modal-close",
            type: "button",
            onClick: props.onClose,
            "aria-label": "Close jump selector",
          },
          h(UiIcon, { name: "close" })
        )
      ),
      h(
        "div",
        { className: "jump-turn-form" },
        h(
          "label",
          { className: "matches-modal-field" },
          h("span", null, "Round"),
          h("input", {
            type: "number",
            min: 1,
            max: maxRoundNumber,
            step: 1,
            value: String(props.roundIndex + 1),
            onInput: (event) => {
              const nextValue = Number(event.target.value);
              if (Number.isNaN(nextValue)) {
                return;
              }

              props.onRoundChange(Math.max(0, Math.min(maxRoundNumber - 1, nextValue - 1)));
            },
          })
        ),
        h(
          "label",
          { className: "matches-modal-field" },
          h("span", null, "Turn"),
          h("input", {
            type: "number",
            min: 1,
            max: maxTurnNumber,
            step: 1,
            value: String(props.turnIndex + 1),
            onInput: (event) => {
              const nextValue = Number(event.target.value);
              if (Number.isNaN(nextValue)) {
                return;
              }

              props.onTurnChange(Math.max(0, Math.min(maxTurnNumber - 1, nextValue - 1)));
            },
          })
        )
      ),
      h(
        "div",
        { className: "jump-turn-actions" },
        h(
          "button",
          { className: "matches-modal-reset", type: "button", onClick: props.onClose },
          "Cancel"
        ),
        h(
          "button",
          {
            className: "matches-modal-link jump-turn-apply",
            type: "button",
            onClick: () => props.onApply(props.roundIndex, props.turnIndex),
          },
          "Jump To Selection"
        )
      )
    )
  );
}

function MatchSidebarPanel(props) {
  const maxAverage = Math.max(...props.model.averageScores.map((entry) => entry.score || 0), 1);
  const panelTitle = props.model.matchName || "Match Replay";
  const playPauseLabel = props.isRunning ? "Pause" : "Play";
  const playPauseIcon = props.isRunning ? "pause" : "play_arrow";
  const [isJumpModalOpen, setJumpModalOpen] = useState(false);
  const [selectedRoundIndex, setSelectedRoundIndex] = useState(props.model.currentRoundIndex || 0);
  const [selectedTurnIndex, setSelectedTurnIndex] = useState(props.model.turnNumber || 0);

  useEffect(() => {
    if (!isJumpModalOpen) {
      setSelectedRoundIndex(props.model.currentRoundIndex || 0);
      setSelectedTurnIndex(props.model.turnNumber || 0);
    }
  }, [isJumpModalOpen, props.model.currentRoundIndex, props.model.turnNumber]);

  useEffect(() => {
    const selectedRound = props.model.roundOptions?.[selectedRoundIndex];
    const maxTurnIndex = Math.max((selectedRound?.turns?.length || 1) - 1, 0);
    if (selectedTurnIndex > maxTurnIndex) {
      setSelectedTurnIndex(maxTurnIndex);
    }
  }, [props.model.roundOptions, selectedRoundIndex, selectedTurnIndex]);

  return h(
    Fragment,
    null,
    h(
      CardShell,
      { className: "replay-sidebar-panel" },
      h(
        "div",
        { className: "panel-header match-sidebar-header" },
        h(
          "div",
          { className: "match-sidebar-heading" },
          h("p", { className: "shell-eyebrow match-sidebar-eyebrow", title: panelTitle }, panelTitle)
        ),
        h(
          "div",
          { className: "hero-controls hero-controls--sidebar" },
          h(
            "button",
            {
              className: "top-app-bar__menu hero-controls__menu",
              type: "button",
              onClick: props.onToggleMenu,
              "aria-label": "Toggle navigation",
            },
            h(UiIcon, { name: "menu" })
          ),
          h(
            "div",
            { className: "top-app-bar__counter" },
            h(UiIcon, { name: "timer", className: "top-app-bar__counter-icon" }),
            h(
              "div",
              { className: "top-app-bar__counter-copy" },
              h("span", null, `Round ${props.roundNumber + 1}`),
              h("strong", null, `Turn ${props.turnNumber + 1}`)
            )
          ),
          h(
            "div",
            { className: "sidebar-playback-grid" },
            h(
              "div",
              { className: "sidebar-playback-grid__prev" },
              h(PlaybackButton, { label: "Prev", icon: "skip_previous", onClick: props.onPrev, disabled: !props.canStepBack })
            ),
            h(
              "div",
              { className: "sidebar-playback-grid__toggle" },
              h(PlaybackButton, { label: playPauseLabel, icon: playPauseIcon, onClick: props.onTogglePlay })
            ),
            h(
              "div",
              { className: "sidebar-playback-grid__next" },
              h(PlaybackButton, { label: "Next", icon: "skip_next", onClick: props.onNext, disabled: !props.canStepForward })
            ),
            h(
              "div",
              { className: "sidebar-playback-grid__jump" },
              h(
                "button",
                {
                  className: "sidebar-jump-button",
                  type: "button",
                  onClick: () => setJumpModalOpen(true),
                },
                h(UiIcon, { name: "my_location" }),
                h("span", null, "Jump To Round / Turn")
              )
            )
          )
        )
      ),
      h(
        "div",
        { className: "section-block" },
        h(
          "div",
          { className: "section-header-row" },
          h("p", { className: "section-heading" }, "Leaderboard"),
          h("span", { className: "section-badge" }, `${props.model.leaderboard.length} Players`)
        ),
        h(
          "div",
          { className: "scanner-stack" },
          props.model.leaderboard.map((entry) =>
            h(ScannerRowCard, {
              key: `leaderboard-${entry.playerId}`,
              accentColor: entry.color,
              leader: entry.place === 1,
              rank: String(entry.place).padStart(2, "0"),
              title: entry.name,
              subtitle: `${entry.remainingTrains} trains left`,
              value: String(entry.score),
              onClick: props.onSelectPlayer ? () => props.onSelectPlayer(entry.playerId) : undefined,
            })
          )
        )
      ),
      h(
        "div",
        { className: "section-block" },
        h("p", { className: "section-heading" }, "Historical Performance"),
        h(
          "div",
          { className: "scanner-stack" },
          props.model.averageScores.map((entry) =>
            h(MetricRowCard, {
              key: `average-${entry.playerId}`,
              accentColor: entry.color,
              title: entry.name,
              value: entry.score == null ? "--" : String(entry.score),
              widthPercent: Math.max(8, ((entry.score || 0) / maxAverage) * 100),
            })
          )
        )
      )
    ),
    h(JumpToTurnModal, {
      isOpen: isJumpModalOpen,
      roundOptions: props.model.roundOptions,
      roundIndex: selectedRoundIndex,
      turnIndex: selectedTurnIndex,
      onRoundChange: setSelectedRoundIndex,
      onTurnChange: setSelectedTurnIndex,
      onClose: () => setJumpModalOpen(false),
      onApply: (roundIndex, turnIndex) => {
        props.onJumpTo(roundIndex, turnIndex);
        setJumpModalOpen(false);
      },
    })
  );
}

export { MatchSidebarPanel };
