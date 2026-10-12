const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

/** "Oct 12, 2026" from an ISO timestamp. */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

/** "1.4 GB", "812.3 MB", "42 KB", "900 B". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** "2h 14m 3s", "14m 3s", "45s". */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** "00:03:18" — always HH:MM:SS so multi-hour videos line up. */
export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

/** "29.97 fps" or "30 fps". */
export function formatFps(fps: number): string {
  return `${Number.isInteger(fps) ? fps : fps.toFixed(2)} fps`;
}
