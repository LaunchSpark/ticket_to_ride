import { h } from "../runtime.jsx";

function StatusScreen(props) {
  return h(
    "div",
    { className: "status-screen" },
    h(
      "div",
      { className: "status-card" },
      h("p", { className: "shell-eyebrow" }, props.label || "Replay Status"),
      h("h2", null, props.title),
      h("p", null, props.message)
    )
  );
}

export { StatusScreen };
