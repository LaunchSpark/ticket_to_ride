// Player roster panel shown beside the route graph. Renders one row per
// seat from the `players` trait ({id, name, color} dicts, the shape
// HarnessGame.roster() produces): a swatch in the seat color - the same
// color used for that player's claim markers on the board - plus a name.
function render({ model, el }) {
    el.classList.add("player-list-widget");

    const draw = () => {
        el.replaceChildren();

        const heading = document.createElement("div");
        heading.className = "player-list-heading";
        heading.textContent = "Players";
        el.appendChild(heading);

        (model.get("players") || []).forEach((player) => {
            const row = document.createElement("div");
            row.className = "player-list-row";

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
}

export default { render };
