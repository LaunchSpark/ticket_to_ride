import { h } from "../runtime.jsx";
import { UiIcon } from "./UiIcon.jsx";

function ShellNavItem(props) {
  const className = props.active ? "shell-nav-item is-active" : "shell-nav-item";
  return h(
    props.href ? "a" : "button",
    {
      className,
      href: props.href,
      target: props.external ? "_blank" : undefined,
      rel: props.external ? "noreferrer" : undefined,
      type: props.href ? undefined : "button",
      onClick: props.onClick,
      title: props.title,
      "aria-current": props.active ? "page" : undefined,
    },
    h("span", { className: "shell-nav-mark", "aria-hidden": "true" }, h(UiIcon, { name: props.icon, className: "shell-nav-mark-icon" })),
    h(
      "span",
      { className: "shell-nav-copy" },
      h("strong", null, props.label),
      h("small", null, props.description)
    )
  );
}

export { ShellNavItem };
