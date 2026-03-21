import { h, useEffect, useRef, useState } from "../../runtime.jsx";
import { CardShell } from "../../atoms/CardShell.jsx";
import { RouteOverlay } from "./RouteOverlay.jsx";

const MAP_WIDTH = 966;
const MAP_HEIGHT = 640;
const MAP_ASPECT_RATIO = MAP_WIDTH / MAP_HEIGHT;

function MapRoutesPanel(props) {
  const stageRef = useRef(null);
  const [frameSize, setFrameSize] = useState({ width: MAP_WIDTH, height: MAP_HEIGHT });

  useEffect(() => {
    if (!stageRef.current) {
      return undefined;
    }

    const updateFrameSize = () => {
      if (!stageRef.current) {
        return;
      }

      const { width, height } = stageRef.current.getBoundingClientRect();
      if (!width || !height) {
        return;
      }

      let nextWidth = width;
      let nextHeight = width / MAP_ASPECT_RATIO;

      if (nextHeight > height) {
        nextHeight = height;
        nextWidth = height * MAP_ASPECT_RATIO;
      }

      setFrameSize({
        width: Math.round(nextWidth),
        height: Math.round(nextHeight),
      });
    };

    updateFrameSize();

    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(stageRef.current);
    window.addEventListener("resize", updateFrameSize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateFrameSize);
    };
  }, []);

  return h(
    CardShell,
    { className: "replay-hero-panel" },
    h(
      "div",
      { className: "hero-board-stage", ref: stageRef },
      h(
        "div",
        {
          className: "hero-map-frame",
          style: {
            width: `${frameSize.width}px`,
            height: `${frameSize.height}px`,
          },
        },
        h("div", { className: "hero-map-vignette", "aria-hidden": "true" }),
        h("img", { className: "hero-map-image", src: "img/USA_map-1.png", alt: "Ticket to Ride USA map" }),
        props.routeMarkup
          ? h(RouteOverlay, { routeMarkup: props.routeMarkup, routeClaims: props.model.routeClaims })
          : h("div", { className: "route-overlay route-overlay-loading" }, "Loading routes...")
      ),
    )
  );
}

export { MapRoutesPanel };
