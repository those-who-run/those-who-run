// Not a route: what the Node import test must catch (ADR 0003 point 3, #237 AC5).
// Reading `window` at module top level breaks server rendering.
const width = window.innerWidth;

export function Component() {
  return <p>{width}</p>;
}
