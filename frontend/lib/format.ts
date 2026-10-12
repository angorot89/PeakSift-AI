const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

/** "Oct 12, 2026" from an ISO timestamp. */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}
