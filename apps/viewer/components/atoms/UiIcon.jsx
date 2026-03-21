import { h } from "../runtime.jsx";

function UiIcon(props) {
  const className = props.className ? `material-symbols-outlined ${props.className}` : "material-symbols-outlined";
  return h(
    "span",
    {
      className,
      "aria-hidden": props.label ? undefined : "true",
      title: props.label,
    },
    props.name
  );
}

export { UiIcon };
