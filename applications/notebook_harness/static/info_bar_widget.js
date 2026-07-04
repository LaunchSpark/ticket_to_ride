// src/info_bar_widget.js
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
var info_bar_widget_default = { render };
export {
  info_bar_widget_default as default
};
