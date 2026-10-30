// Bringing a settings card into view without moving the page: the editor's settings panel scrolls
// on its own (large screens), and a selection on the timeline must never scroll the timeline away.

/** Scrolls `node` into view inside its nearest `[data-scroll-panel]` only; the window stays. */
export function revealInPanel(node: HTMLElement | null, margin = 8) {
  const panel = node?.closest<HTMLElement>("[data-scroll-panel]");
  if (!node || !panel || panel.scrollHeight <= panel.clientHeight) return;
  const n = node.getBoundingClientRect();
  const p = panel.getBoundingClientRect();
  const delta = n.top < p.top ? n.top - p.top - margin : n.bottom > p.bottom ? n.bottom - p.bottom + margin : 0;
  if (delta) panel.scrollBy({ top: delta, behavior: "smooth" });
}
