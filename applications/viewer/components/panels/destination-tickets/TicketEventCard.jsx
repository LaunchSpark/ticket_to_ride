import { h } from "../../runtime.jsx";

function TicketEventCard(props) {
  const { accentColor, ticket } = props;
  return h(
    "article",
    { className: "event-ticket-card" },
    h("span", {
      className: "scanner-row-accent",
      style: { background: ticket.completed ? "#3fff8b" : accentColor },
    }),
    h(
      "div",
      { className: "event-ticket-copy" },
      h("small", null, `Ticket ${String(ticket.sequence).padStart(2, "0")}`),
      h("strong", null, `${ticket.from} -> ${ticket.to}`)
    ),
    h(
      "div",
      { className: "event-ticket-meta" },
      h("span", { className: ticket.completed ? "result-pill result-pill--complete" : "result-pill" }, ticket.completed ? "Completed" : "Open"),
      h("span", { className: "ticket-points" }, `${ticket.points} pts`)
    )
  );
}

export { TicketEventCard };
