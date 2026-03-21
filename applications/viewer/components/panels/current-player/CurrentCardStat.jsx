import { h } from "../../runtime.jsx";
import { PLAYER_COLORS } from "../../constants.jsx";

function CurrentCardStat(props) {
  const { card } = props;
  const chipBackground =
    card.color === "locomotive"
      ? "linear-gradient(135deg, #ff8f73, #6e9bff, #3fff8b)"
      : PLAYER_COLORS[card.color] || "#ff8f73";

  return h(
    "article",
    { className: "current-card-stat" },
    h("span", {
      className: "current-card-chip",
      style: { background: chipBackground },
      title: card.label,
    }),
    h("span", { className: "current-card-label" }, card.label),
    h("strong", { className: "current-card-count" }, String(card.count))
  );
}

export { CurrentCardStat };
