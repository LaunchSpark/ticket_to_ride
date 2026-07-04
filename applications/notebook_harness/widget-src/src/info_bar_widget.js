// Placeholder information bar shown below the map and player list. It will
// eventually surface the train-card market and the odds of drawing each card
// color, derived from public information only; for now it just reserves the
// space so the notebook layout is already in its final shape.
function render({ model, el }) {
    el.classList.add("info-bar-widget");

    const label = document.createElement("span");
    label.className = "info-bar-placeholder";

    const draw = () => {
        label.textContent = model.get("placeholder_text") || "";
    };

    draw();
    model.on("change:placeholder_text", draw);
    el.appendChild(label);
}

export default { render };
