import { h, useEffect, useRef } from "../../runtime.jsx";

function normalizeClaimedRouteId(routeId) {
  const parts = String(routeId || "").split("-");
  if (parts.length < 3) {
    return String(routeId || "");
  }

  const lastPart = parts[parts.length - 1];
  const maybeIndex = /^\d+$/.test(lastPart);
  if (maybeIndex && parts.length >= 4) {
    return `${parts.slice(0, -2).join("-")}-${lastPart}`;
  }

  return parts.slice(0, -1).join("-");
}

function applyClaimedRoutes(rootNode, routeClaims) {
  const svg = rootNode.querySelector("svg");
  if (!svg) {
    return;
  }

  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");

  const paths = Array.from(svg.querySelectorAll("path"));
  paths.forEach((path) => {
    const originalStroke = path.getAttribute("data-base-stroke") || path.getAttribute("stroke") || "#d9d9d9";
    path.setAttribute("data-base-stroke", originalStroke);
    path.setAttribute("stroke", originalStroke);
    path.setAttribute("opacity", "0.42");
    path.style.filter = "none";
    path.style.strokeLinecap = "round";
    path.style.strokeLinejoin = "round";
  });

  routeClaims.forEach((claim) => {
    const normalizedRouteId = normalizeClaimedRouteId(claim.routeId);
    const matchingRoutes = paths.filter((path) => {
      const pathId = path.id || "";
      return pathId === normalizedRouteId || pathId.startsWith(`${normalizedRouteId}-`);
    });
    for (const route of matchingRoutes) {
      route.setAttribute("stroke", claim.color);
      route.setAttribute("opacity", "1");
      route.style.filter = `drop-shadow(0 0 4px ${claim.color}) drop-shadow(0 0 10px ${claim.color})`;
      break;
    }
  });
}

function RouteOverlay(props) {
  const overlayRef = useRef(null);

  useEffect(() => {
    if (!overlayRef.current || !props.routeMarkup) {
      return;
    }
    overlayRef.current.innerHTML = props.routeMarkup;
    applyClaimedRoutes(overlayRef.current, props.routeClaims);
  }, [props.routeMarkup, props.routeClaims]);

  return h("div", {
    ref: overlayRef,
    className: "route-overlay",
    "aria-hidden": "true",
  });
}

export { RouteOverlay, normalizeClaimedRouteId };
