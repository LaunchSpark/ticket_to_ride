import { h } from "../../runtime.jsx";

function MetricRowCard(props) {
  return h(
    "article",
    { className: "scanner-row-card scanner-row-card--soft scanner-row-card--metric" },
    h("span", { className: "scanner-row-accent", style: { background: props.accentColor } }),
    h(
      "div",
      { className: "scanner-row-copy scanner-row-copy--metric" },
      h("strong", null, props.title),
      h(
        "div",
        { className: "metric-bar-track" },
        h("span", {
          className: "metric-bar-fill",
          style: { width: `${props.widthPercent}%`, background: props.accentColor },
        })
      )
    ),
    h("span", { className: "scanner-row-value" }, props.value)
  );
}

export { MetricRowCard };
