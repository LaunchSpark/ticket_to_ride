import { h } from "../../runtime.jsx";
import { UiIcon } from "../../atoms/UiIcon.jsx";

function MarketSlot(props) {
  if (props.endpointLabel) {
    return h(
      "div",
      { className: "market-slot market-slot--endpoint" },
      h(UiIcon, { name: props.endpointIcon, className: "market-slot-endpoint-icon" }),
      h("strong", null, props.endpointLabel)
    );
  }

  return h(
    "div",
    { className: "market-slot" },
    props.imageSrc
      ? h("img", {
          src: props.imageSrc,
          alt: props.alt,
          onError: (event) => {
            event.currentTarget.style.display = "none";
            const fallback = event.currentTarget.parentElement?.querySelector(".market-slot-fallback");
            if (fallback) {
              fallback.hidden = false;
            }
          },
        })
      : h("span", { className: "market-slot-fallback" }, props.fallback)
    ,
    props.imageSrc
      ? h(
          "span",
          {
            className: "market-slot-fallback",
            hidden: true,
          },
          props.fallback
        )
      : null
  );
}

export { MarketSlot };
