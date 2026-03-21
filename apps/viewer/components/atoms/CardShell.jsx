import { h } from "../runtime.jsx";

function CardShell(props) {
  return h(
    "section",
    { className: `replay-panel ${props.className || ""}`.trim() },
    h("div", { className: "panel-scanline", "aria-hidden": "true" }),
    props.children
  );
}

export { CardShell };
