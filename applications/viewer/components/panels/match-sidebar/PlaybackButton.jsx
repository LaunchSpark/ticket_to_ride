import { h } from "../../runtime.jsx";
import { UiIcon } from "../../atoms/UiIcon.jsx";

function PlaybackButton(props) {
  return h(
    "button",
    {
      type: "button",
      className: "playback-button",
      onClick: props.onClick,
      disabled: props.disabled,
      "aria-label": props.label,
    },
    props.icon
      ? h(
          "span",
          { className: "playback-button-icon" },
          h(UiIcon, { name: props.icon, className: "playback-button-icon-symbol" })
        )
      : null,
    h("span", { className: "playback-button-label" }, props.label)
  );
}

export { PlaybackButton };
