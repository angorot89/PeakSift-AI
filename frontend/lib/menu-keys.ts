// Pure keyboard movement for menus and lists (no React): which item a key moves focus to.

/** The index focus moves to for an arrow/Home/End key, wrapping around; null for other keys. */
export function menuIndex(key: string, current: number, count: number): number | null {
  if (count <= 0) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowDown") return current < 0 ? 0 : (current + 1) % count;
  if (key === "ArrowUp") return current < 0 ? count - 1 : (current - 1 + count) % count;
  return null;
}

/** The tab index for a key in a horizontal tab list (Left/Right, Home/End), wrapping; else null. */
export function tabKeyIndex(key: string, current: number, count: number): number | null {
  const vertical = key === "ArrowRight" ? "ArrowDown" : key === "ArrowLeft" ? "ArrowUp" : key;
  return key === "ArrowDown" || key === "ArrowUp" ? null : menuIndex(vertical, current, count);
}
