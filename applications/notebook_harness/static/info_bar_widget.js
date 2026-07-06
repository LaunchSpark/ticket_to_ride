// src/info_bar_widget.js
var BIN_ICON = `
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M3 6h18"/>
  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
  <line x1="10" y1="11" x2="10" y2="17"/>
  <line x1="14" y1="11" x2="14" y2="17"/>
</svg>`;
function pie_slice_path(cx, cy, r, start_angle, end_angle) {
  const large_arc = end_angle - start_angle > Math.PI ? 1 : 0;
  const x0 = cx + r * Math.cos(start_angle);
  const y0 = cy + r * Math.sin(start_angle);
  const x1 = cx + r * Math.cos(end_angle);
  const y1 = cy + r * Math.sin(end_angle);
  return `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large_arc} 1 ${x1} ${y1} Z`;
}
function build_pie(segments, colors, label) {
  const size = 96;
  const c = size / 2;
  const r = c - 2;
  const total = segments.reduce((sum, seg) => sum + seg.count, 0);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.classList.add("market-pie");
  if (!total) {
    return svg;
  }
  if (segments.length === 1) {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", c);
    circle.setAttribute("cy", c);
    circle.setAttribute("r", r);
    circle.setAttribute("fill", colors[segments[0].color] || "#999");
    svg.appendChild(circle);
    return svg;
  }
  let angle = -Math.PI / 2;
  for (const seg of segments) {
    const sweep = seg.count / total * 2 * Math.PI;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pie_slice_path(c, c, r, angle, angle + sweep));
    path.setAttribute("fill", colors[seg.color] || "#999");
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    const pct = (100 * seg.count / total).toFixed(1);
    title.textContent = `${seg.color}: ${seg.count} (${pct}%) \u2014 ${label}`;
    path.appendChild(title);
    svg.appendChild(path);
    angle += sweep;
  }
  return svg;
}
function build_counted_card(count, className, inner) {
  const wrap = document.createElement("div");
  wrap.className = "market-slot";
  const number = document.createElement("div");
  number.className = "market-count";
  number.textContent = String(count);
  const card = document.createElement("div");
  card.className = `market-card ${className}`;
  if (inner) {
    card.innerHTML = inner;
  }
  wrap.appendChild(number);
  wrap.appendChild(card);
  return wrap;
}
function render({ model, el }) {
  el.classList.add("info-bar-widget");
  const draw = () => {
    el.replaceChildren();
    const market = model.get("market") || {};
    const colors = market.colors || {};
    const row = document.createElement("div");
    row.className = "market-row";
    for (const letter of market.face_up || []) {
      const wrap = document.createElement("div");
      wrap.className = "market-slot";
      const spacer = document.createElement("div");
      spacer.className = "market-count market-count-empty";
      const card = document.createElement("div");
      card.className = "market-card";
      card.style.background = colors[letter] || "#999";
      if (letter === "L") {
        card.classList.add("market-card-locomotive");
      }
      card.title = letter;
      wrap.appendChild(spacer);
      wrap.appendChild(card);
      row.appendChild(wrap);
    }
    row.appendChild(
      build_counted_card(market.deck_count ?? 0, "market-card-deck", "")
    );
    row.appendChild(
      build_counted_card(market.discard_count ?? 0, "market-card-discard", BIN_ICON)
    );
    el.appendChild(row);
    const pie_wrap = document.createElement("div");
    pie_wrap.className = "market-pie-wrap";
    pie_wrap.appendChild(build_pie(market.pie || [], colors, market.pie_label || ""));
    const pie_label = document.createElement("div");
    pie_label.className = "market-pie-label";
    pie_label.textContent = market.pie_label || "";
    pie_wrap.appendChild(pie_label);
    el.appendChild(pie_wrap);
  };
  draw();
  model.on("change:market", draw);
}
var info_bar_widget_default = { render };
export {
  info_bar_widget_default as default
};
