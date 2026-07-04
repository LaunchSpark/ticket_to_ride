// Player roster panel shown beside the route graph. Renders one row per
// seat from the `players` trait ({id, name, color} dicts, the shape
// HarnessGame.roster() produces): a swatch in the seat color - the same
// color used for that player's claim markers on the board - plus a name.
//
// Rows act as a self-clearing radio group over the `selected_player` trait:
// click a player to select them, click another to move the selection, click
// the selected one again to clear it ("" = nobody selected, the default).
function render({ model, el }) {
    el.classList.add("player-list-widget");

    const toggle_selection = (playerId) => {
        const current = model.get("selected_player") || "";
        model.set("selected_player", current === playerId ? "" : playerId);
        model.save_changes();
    };

    const draw = () => {
        el.replaceChildren();
        const selected = model.get("selected_player") || "";

        const heading = document.createElement("div");
        heading.className = "player-list-heading";
        heading.textContent = "Players";
        el.appendChild(heading);

        (model.get("players") || []).forEach((player) => {
            const row = document.createElement("div");
            row.className = "player-list-row" + (player.id === selected ? " selected" : "");
            row.addEventListener("click", () => toggle_selection(player.id));

            const swatch = document.createElement("span");
            swatch.className = "player-list-swatch";
            swatch.style.background = player.color || "#999999";

            const name = document.createElement("span");
            name.className = "player-list-name";
            name.textContent = player.name || player.id;

            row.appendChild(swatch);
            row.appendChild(name);
            el.appendChild(row);
        });
    };

    draw();
    model.on("change:players", draw);
    model.on("change:selected_player", draw);
}

export default { render };
