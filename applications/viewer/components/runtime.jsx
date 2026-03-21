const {
  createElement: h,
  Fragment,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} = React;

const RUN_TRANSITION = startTransition || ((callback) => callback());

export {
  Fragment,
  RUN_TRANSITION,
  h,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
};
