import { h } from "../../runtime.jsx";
import { CardShell } from "../../atoms/CardShell.jsx";
import { MarketSlot } from "./MarketSlot.jsx";

function MarketStrip(props) {
  return h(
    CardShell,
    { className: "replay-market-panel" },
    h(
      "div",
      { className: "market-strip" },
      props.marketCards.map((card) =>
        h(MarketSlot, {
          key: card.id,
          imageSrc: card.imageSrc,
          alt: `Market card ${card.code}`,
          fallback: card.code,
        })
      ),
      h(MarketSlot, { endpointIcon: "style", endpointLabel: "Deck" }),
      h(MarketSlot, { endpointIcon: "confirmation_number", endpointLabel: "Tickets" })
    )
  );
}

export { MarketStrip };
