// widget-src/src/spectate_stats_modal.js
import { renderStatsCard } from "./spectate_shell_widget.js";

function openStatsModal(model, shellRoot, playerId) {
    if (!shellRoot || shellRoot.querySelector(".shell-stats-backdrop")) return;

    const backdrop = document.createElement("div");
    backdrop.className = "shell-stats-backdrop";
    const dialog = document.createElement("div");
    dialog.className = "shell-stats-modal";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");

    const close = () => {
        backdrop.remove();
        document.removeEventListener("keydown", onKey);
        if (model.off) model.off("change:stats", refresh);
    };
    const onKey = (event) => { if (event.key === "Escape") close(); };

    const header = document.createElement("div");
    header.className = "shell-stats-modal-header";
    const title = document.createElement("p");
    title.className = "shell-eyebrow";
    title.textContent = "Player Stats";
    const closeButton = document.createElement("button");
    closeButton.className = "shell-playback-button";
    closeButton.textContent = "✕";
    closeButton.setAttribute("aria-label", "Close player stats");
    closeButton.addEventListener("click", close);
    header.append(title, closeButton);

    const body = document.createElement("div");
    const refresh = () => body.replaceChildren(renderStatsCard(model, playerId));
    refresh();
    model.on("change:stats", refresh);

    dialog.append(header, body);
    dialog.addEventListener("click", (event) => event.stopPropagation());
    backdrop.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    backdrop.appendChild(dialog);
    shellRoot.appendChild(backdrop);
}

export { openStatsModal };
