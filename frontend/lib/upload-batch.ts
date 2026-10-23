// One summary for a batch of uploads (several files dropped at once): one progress bar and one
// line of text instead of a row or a toast per file. Failures are still listed one by one.

export type BatchState = "uploading" | "processing" | "done" | "existing" | "failed";
export type BatchItem = { size: number; state: BatchState; progress: number };

export type BatchSummary = {
  total: number;
  finished: number;
  failed: number;
  /** Still uploading or being checked. */
  working: boolean;
  /** Overall progress by size, over the files that have not failed (0–100). */
  percent: number;
  label: string;
};

const files = (n: number) => `${n} ${n === 1 ? "file" : "files"}`;

export function batchSummary(items: BatchItem[]): BatchSummary {
  const total = items.length;
  const failed = items.filter((item) => item.state === "failed").length;
  const finished = items.filter((item) => item.state === "done" || item.state === "existing" || item.state === "failed").length;
  const existing = items.filter((item) => item.state === "existing").length;
  const counted = items.filter((item) => item.state !== "failed");
  const bytes = counted.reduce((sum, item) => sum + Math.max(item.size, 1), 0);
  const sent = counted.reduce(
    (sum, item) => sum + Math.max(item.size, 1) * (item.state === "uploading" ? item.progress : 100) / 100,
    0,
  );
  const percent = bytes ? Math.round((sent / bytes) * 100) : 0;
  const working = finished < total;
  const added = total - failed;
  let label: string;
  if (working) label = `Adding ${files(total)} · ${finished} of ${total} done`;
  else if (failed) label = `${added ? `${files(added)} added · ` : ""}${failed} couldn't be added`;
  else label = `${files(total)} added${existing ? ` (${existing} already in this project)` : ""}`;
  return { total, finished, failed, working, percent, label };
}
