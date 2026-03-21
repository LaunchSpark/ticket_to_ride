import { h } from "../../runtime.jsx";

function ScannerRowCard(props) {
  const className = props.leader ? "scanner-row-card scanner-row-card--leader" : "scanner-row-card";
  const element = props.onClick ? "button" : "article";

  return h(
    element,
    {
      className: props.onClick ? `${className} scanner-row-card--interactive` : className,
      type: props.onClick ? "button" : undefined,
      onClick: props.onClick,
    },
    h("span", { className: "scanner-row-accent", style: { background: props.accentColor } }),
    h("span", { className: "scanner-row-rank" }, props.rank),
    h(
      "div",
      { className: "scanner-row-copy" },
      h("strong", null, props.title),
      h("small", null, props.subtitle)
    ),
    h("span", { className: "scanner-row-value" }, props.value)
  );
}

export { ScannerRowCard };
