import { h } from "../../runtime.jsx";
import { PLAYER_COLORS } from "../../constants.jsx";
import { CardShell } from "../../atoms/CardShell.jsx";
import { TicketEventCard } from "./TicketEventCard.jsx";

function DestinationTicketsPanel(props) {
  const accentColor = PLAYER_COLORS[props.player.meta.color] || props.player.meta.color || "#ff8f73";

  return h(
    CardShell,
    { className: "replay-ticket-panel" },
    h(
      "div",
      { className: "panel-header" },
      h(
        "div",
        null,
        h("p", { className: "shell-eyebrow" }, "Latest Events Slot"),
        h("h2", { className: "panel-title" }, "Destination Tickets")
      ),
      h("span", { className: "panel-subtle-label" }, props.player.meta.name)
    ),
    props.tickets.length
      ? h(
          "div",
          { className: "events-stack" },
          props.tickets.map((ticket) => h(TicketEventCard, { key: ticket.id, accentColor, ticket }))
        )
      : h("div", { className: "empty-card-message" }, "No destination tickets on this turn.")
  );
}

export { DestinationTicketsPanel };
